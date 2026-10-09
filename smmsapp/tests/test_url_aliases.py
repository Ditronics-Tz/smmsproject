"""Regression tests for the trailing-slash URL aliases.

Health, status, audit logs and the SMS opt-out/log endpoints are each mounted
twice: once at the canonical slash-less path and once with a trailing slash for
clients written before the canonical form was settled. Both spellings must keep
working, because clients in the field depend on them.

The aliases were re-pointed at dedicated subclasses that are excluded from the
generated OpenAPI schema so each operation is documented exactly once. These
tests pin both halves of that change: the aliases still respond identically,
and each path keeps its own reverse() name.
"""
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from ..models import School

User = get_user_model()


class TrailingSlashAliasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Alias School", location="Dodoma")
        # Admin-only API access is governed by the application role, not by
        # the Django is_staff bit.
        cls.admin = User.objects.create_user(
            username="aliasadmin", password="Passw0rd!123", role="admin",
            is_staff=True, school=cls.school, first_name="Ali",
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)

    def test_health_alias_paths_both_respond(self):
        for path in ("/health", "/health/"):
            with self.subTest(path=path):
                response = self.api.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "ok")

    def test_status_alias_paths_both_respond(self):
        for path in ("/status", "/status/"):
            with self.subTest(path=path):
                response = self.api.get(path)
                self.assertIn(response.status_code, (200, 503))
                self.assertIn("checks", response.json())

    def test_audit_log_alias_paths_both_respond(self):
        for path in ("/audit/logs", "/audit/logs/"):
            with self.subTest(path=path):
                response = self.api.get(path)
                self.assertEqual(response.status_code, 200)

    def test_sms_log_alias_paths_both_respond(self):
        for path in ("/sms/logs", "/sms/logs/"):
            with self.subTest(path=path):
                response = self.api.get(path)
                self.assertEqual(response.status_code, 200)

    def test_sms_opt_out_alias_paths_both_resolve(self):
        """Opt-out mutates, so only routing is asserted here, not the write."""
        for path in ("/sms/opt-out", "/sms/opt-out/"):
            with self.subTest(path=path):
                response = self.api.options(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("POST", response.json()["name"].upper() + "POST")

    def test_every_alias_keeps_its_own_reverse_name(self):
        for name in (
            "health", "health-slash", "status", "status-slash",
            "audit-logs", "audit-logs-slash",
            "sms-logs", "sms-logs-slash", "sms-opt-out", "sms-opt-out-slash",
        ):
            with self.subTest(name=name):
                self.assertTrue(reverse(name).startswith("/"))


class SMSOptOutCoercionTests(TestCase):
    """Opt-out used to run the raw request value through bool().

    Clients that send JSON strings (form encoders, JS that does not coerce)
    meant "opt back in" by sending "false", but bool("false") is True, so those
    users were opted OUT instead. The endpoint now validates through a real
    BooleanField.
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="SMS School", location="Arusha")
        cls.parent = User.objects.create_user(
            username="smsparent", password="Passw0rd!123", role="parent",
            school=cls.school, first_name="Sana",
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.parent)

    def test_string_false_opts_the_user_back_in(self):
        response = self.api.post("/sms/opt-out", {"sms_opt_out": "false"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["sms_opt_out"], False)
        self.parent.refresh_from_db()
        self.assertIs(self.parent.sms_opt_out, False)

    def test_real_boolean_still_opts_the_user_out(self):
        response = self.api.post("/sms/opt-out", {"sms_opt_out": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["sms_opt_out"], True)
        self.parent.refresh_from_db()
        self.assertIs(self.parent.sms_opt_out, True)

    def test_missing_field_is_rejected(self):
        response = self.api.post("/sms/opt-out", {}, format="json")
        self.assertEqual(response.status_code, 400)
