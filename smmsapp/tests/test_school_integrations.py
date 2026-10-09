import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from smmsapp.models import (
    AuditLog, IntegrationClass, IntegrationKey, IntegrationSyncLog, School,
    WebhookDelivery, WebhookEndpoint,
)
from smmsapp.services.webhooks import webhook_signature
from smmsapp.tasks import deliver_webhook
from smmsapp.integrations.adapters.csv_adapter import CSVSchoolAdapter
from smmsapp.tasks import sync_school_system


User = get_user_model()


@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {"integration": "120/min"},
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
})
class SchoolIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Integration School", location="Arusha")
        cls.admin = User.objects.create_user(
            username="integration-admin", password="Passw0rd!123", role="admin",
            is_staff=True, school=cls.school,
        )
        cls.parent = User.objects.create_user(
            username="integration-parent", password="Passw0rd!123", role="parent",
            school=cls.school,
        )
        cls.raw_key = "test-integration-secret-never-store"
        cls.key = IntegrationKey.objects.create(
            name="SIS", key_hash=hashlib.sha256(cls.raw_key.encode()).hexdigest(),
            prefix="ik_test", created_by=cls.admin,
        )

    def setUp(self):
        cache.clear()
        self.api = APIClient()

    def _sync(self, path="/integrations/v1/students/sync", payload=None, key=None):
        return self.api.post(
            path, payload or {"source_system": "sis", "rows": []}, format="json",
            HTTP_X_API_KEY=key or self.raw_key,
        )

    def test_missing_invalid_and_revoked_keys_are_rejected(self):
        no_key = self.api.post("/integrations/v1/students/sync", {"source_system": "sis", "rows": []}, format="json")
        self.assertEqual(no_key.status_code, 401)
        invalid = self._sync(key="not-the-key")
        self.assertEqual(invalid.status_code, 401)
        self.key.revoked_at = __import__("django.utils.timezone", fromlist=["now"]).now()
        self.key.save(update_fields=["revoked_at"])
        revoked = self._sync()
        self.assertEqual(revoked.status_code, 401)

    def test_sync_is_idempotent_and_updates_by_external_identity(self):
        payload = {"source_system": "sis", "rows": [{
            "external_id": "student-14", "first_name": "Asha", "last_name": "Mushi", "class_room": "P4",
        }]}
        first = self._sync(payload=payload)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual((first.data["created"], first.data["updated"], first.data["failed"]), (1, 0, 0))
        payload["rows"][0]["first_name"] = "Asha Updated"
        second = self._sync(payload=payload)
        self.assertEqual(second.data["created"], 0)
        self.assertEqual(second.data["updated"], 1)
        student = User.objects.get(source_system="sis", external_id="student-14")
        self.assertEqual(student.first_name, "Asha Updated")
        self.assertFalse(student.has_usable_password())
        self.assertEqual(IntegrationSyncLog.objects.count(), 2)

    def test_malformed_rows_are_reported_without_aborting_valid_rows(self):
        response = self._sync(payload={"source_system": "sis", "rows": [
            {"external_id": "ok", "first_name": "Juma", "last_name": "Mfaume"},
            {"external_id": "bad", "first_name": "Missing surname"},
        ]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data["created"], response.data["failed"]), (1, 1))
        self.assertEqual(response.data["results"][1]["status"], "failed")

    def test_dry_run_validates_and_logs_but_does_not_upsert(self):
        response = self._sync(payload={"source_system": "sis", "dry_run": True, "rows": [
            {"external_id": "dry-1", "first_name": "Nuru", "last_name": "Mfaume"},
        ]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], 1)
        self.assertFalse(User.objects.filter(source_system="sis", external_id="dry-1").exists())
        self.assertTrue(IntegrationSyncLog.objects.latest("id").dry_run)

    def test_sync_limits_batch_size_and_requires_boolean_dry_run(self):
        oversized = self._sync(payload={"source_system": "sis", "rows": [{}] * 501})
        self.assertEqual(oversized.status_code, 400)
        invalid_bool = self._sync(payload={"source_system": "sis", "rows": [], "dry_run": "false"})
        self.assertEqual(invalid_bool.status_code, 400)

    def test_classes_upsert_within_school(self):
        response = self._sync(
            "/integrations/v1/classes/sync",
            {"source_system": "sis", "rows": [{"external_id": "P4", "name": "Primary 4"}]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(IntegrationClass.objects.get(external_id="P4").name, "Primary 4")

    def test_admin_can_create_key_once_revoke_and_rotate_without_logging_secret(self):
        self.api.force_authenticate(user=self.admin)
        created = self.api.post("/integrations/v1/admin/keys", {"name": "New SIS"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        token = created.data["api_key"]
        key = IntegrationKey.objects.get(pk=created.data["id"])
        self.assertEqual(key.key_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, json.dumps(list(AuditLog.objects.values("before", "after"))))
        rotated = self.api.post(f"/integrations/v1/admin/keys/{key.pk}/rotate", {}, format="json")
        self.assertEqual(rotated.status_code, 201, rotated.data)
        key.refresh_from_db()
        self.assertIsNotNone(key.revoked_at)
        replacement = IntegrationKey.objects.get(pk=rotated.data["id"])
        self.assertNotEqual(replacement.key_hash, key.key_hash)

    def test_parent_cannot_manage_integration_keys(self):
        self.api.force_authenticate(user=self.parent)
        response = self.api.post("/integrations/v1/admin/keys", {"name": "nope"}, format="json")
        self.assertEqual(response.status_code, 403)

    @override_settings(REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
        "DEFAULT_THROTTLE_CLASSES": [],
        "DEFAULT_THROTTLE_RATES": {"integration": "1/min"},
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    })
    def test_sync_rate_limit_is_scoped_to_api_key(self):
        first = self._sync()
        second = self._sync()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_webhook_create_requires_https_and_returns_secret_once(self):
        self.api.force_authenticate(user=self.admin)
        invalid = self.api.post("/integrations/v1/admin/webhooks", {
            "url": "http://sis.example.org/hook", "events": ["meal.purchased"],
        }, format="json")
        self.assertEqual(invalid.status_code, 400)
        valid = self.api.post("/integrations/v1/admin/webhooks", {
            "url": "https://sis.example.org/hook", "events": ["meal.purchased"],
        }, format="json")
        self.assertEqual(valid.status_code, 201, valid.data)
        self.assertTrue(valid.data["secret"])
        listed = self.api.get("/integrations/v1/admin/webhooks")
        self.assertNotIn("secret", listed.data[0])

    def test_webhook_signature_is_hmac_over_exact_body_and_delivery_logs_status(self):
        endpoint = WebhookEndpoint.objects.create(
            school=self.school, url="https://sis.example.org/hook", secret="webhook-test-secret",
            events=["meal.purchased"], created_by=self.admin,
        )
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint, event="meal.purchased", payload={"transaction_id": "txn-1"},
        )
        with patch("smmsapp.services.webhooks._assert_public_https_target", return_value=None), patch("smmsapp.tasks.requests.post") as post:
            post.return_value.status_code = 204
            result = deliver_webhook.apply(args=[str(delivery.pk)]).get()
        self.assertEqual(result, "delivered")
        sent_body = post.call_args.kwargs["data"]
        self.assertEqual(post.call_args.kwargs["headers"]["X-SMMS-Signature"], webhook_signature(endpoint.secret, sent_body))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status_code, 204)
        self.assertIsNotNone(delivery.delivered_at)

    def test_csv_adapter_reads_utf8_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            students = Path(directory) / "students.csv"
            students.write_text("external_id,first_name,last_name\ns-1,Amina,Ali\n", encoding="utf-8")
            with override_settings(SCHOOL_SYSTEM_STUDENTS_CSV=str(students)):
                adapter = CSVSchoolAdapter()
                self.assertEqual(adapter.fetch_students(), [{
                    "external_id": "s-1", "first_name": "Amina", "last_name": "Ali",
                }])

    @override_settings(
        SCHOOL_SYSTEM_INTEGRATION_KEY_ID="",
        SCHOOL_SYSTEM_ADAPTER="csv",
        SCHOOL_SYSTEM_SOURCE="sis",
    )
    def test_scheduled_sync_is_a_safe_noop_without_key_configuration(self):
        self.assertEqual(sync_school_system.apply().get()["configured"], False)

    @override_settings(
        SCHOOL_SYSTEM_INTEGRATION_KEY_ID="1",
        SCHOOL_SYSTEM_ADAPTER="smmsapp.integrations.adapters.csv_adapter.CSVSchoolAdapter",
        SCHOOL_SYSTEM_SOURCE="sis",
        SCHOOL_SYSTEM_SYNC_DRY_RUN=False,
    )
    def test_scheduled_sync_reuses_the_shared_batch_upsert(self):
        with tempfile.TemporaryDirectory() as directory:
            students = Path(directory) / "students.csv"
            students.write_text("external_id,first_name,last_name\ns-scheduled,Hawa,John\n", encoding="utf-8")
            with override_settings(
                SCHOOL_SYSTEM_STUDENTS_CSV=str(students),
                SCHOOL_SYSTEM_PARENTS_CSV="",
                SCHOOL_SYSTEM_CLASSES_CSV="",
            ):
                result = sync_school_system.apply().get()
        self.assertTrue(result["configured"])
        self.assertEqual(result["results"]["students"]["created"], 1)
        self.assertTrue(User.objects.filter(source_system="sis", external_id="s-scheduled").exists())
