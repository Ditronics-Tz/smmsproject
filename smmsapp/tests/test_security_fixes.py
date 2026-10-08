from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ..models import AuditLog, Notification, PasswordResetToken, School, SMSLog
from ..serializers.resources import NotificationSerializer, UserSerializer

User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PasswordNotificationSecurityTests(TestCase):
    """Fix 1: plaintext passwords must never be stored or surfaced via Notification.

    The reset/creation flows now deliver the plaintext password directly to the
    user's email and store a sanitized message in the database instead.
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Azania Secondary", location="Dar es Salaam")
        cls.admin = User.objects.create_user(
            username="admin1", password="Passw0rd!123", role="admin", is_staff=True,
            first_name="Ada", last_name="Admin", school=cls.school,
        )
        cls.parent = User.objects.create_user(
            username="parent1", password="Passw0rd!123", role="parent",
            first_name="Papa", last_name="Mzee", school=cls.school, email="parent1@example.com",
        )

    def setUp(self):
        super().setUp()
        # DRF throttling state lives in the default cache, which is NOT rolled
        # back between tests. Reset it so scoped rates don't leak across cases.
        cache.clear()
        self.api = APIClient()

    def test_forget_password_sends_token_link_not_plaintext(self):
        response = self.api.post("/auth/forgot-password", {"email": self.parent.email})
        self.assertEqual(response.status_code, 200)

        # Email carries a reset token/link — never a plaintext password.
        self.assertEqual(len(mail.outbox), 1)
        email_body = mail.outbox[0].body
        email_msg = mail.outbox[0].message().as_string()

        # The stored notification must NOT embed a plaintext password.
        notification = Notification.objects.filter(recipient=self.parent, title="Reset Password").latest("id")

        # New token-based flow: no auto-generated plaintext password in email or DB.
        self.assertEqual(
            notification.message,
            "A password reset link was sent to your registered email.",
        )
        self.assertNotIn("new password is", email_msg)
        self.assertIn("Reset token:", email_body)
        self.assertIn(self.parent.first_name, email_body)

    def test_create_user_sends_invite_without_persisting_token(self):
        self.api.force_authenticate(user=self.admin)
        payload = {
            "role": "operator",
            "first_name": "Opa",
            "last_name": "Rator",
            "username": "opa1",
            "email": "opa1@example.com",
            "school": str(self.school.id),
        }
        response = self.api.post("/auth/create-user", payload, format="json")
        self.assertEqual(response.status_code, 201)

        user = User.objects.get(username="opa1")
        self.assertFalse(user.has_usable_password())
        self.assertNotIn("invite_link", response.json())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("one-time link", mail.outbox[0].body)
        self.assertNotIn("Password:", mail.outbox[0].body)
        raw_token = mail.outbox[0].body.split("token=")[-1].split()[0]
        token_row = PasswordResetToken.objects.get(user=user)
        self.assertNotEqual(token_row.token_hash, raw_token)
        self.assertNotIn(raw_token, str(list(AuditLog.objects.values("before", "after"))))
        self.assertNotIn(raw_token, str(list(Notification.objects.values_list("message", flat=True))))
        self.assertNotIn(raw_token, str(list(SMSLog.objects.values_list("body", flat=True))))

    def test_create_user_without_contact_returns_invite_once(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post("/auth/create-user", {
            "role": "operator", "first_name": "Nia", "last_name": "NoContact",
            "username": "nia1", "school": str(self.school.id),
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertIn("invite_link", response.json())
        link = response.json()["invite_link"]
        token = link.split("token=")[-1]
        self.assertNotIn(token, str(list(AuditLog.objects.values("before", "after"))))
        self.assertNotIn(token, str(list(Notification.objects.values_list("message", flat=True))))

    def test_invite_link_opens_password_setting_page(self):
        response = self.api.get("/auth/accept-invite")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Set your SMMS password")

    def test_resend_invite_invalidates_previous_token_and_requires_admin(self):
        user = User.objects.create_user(
            username="invitee", password=None, role="operator", first_name="Invited",
            school=self.school,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        old = PasswordResetToken.objects.create(
            user=user,
            token_hash="old-invite-hash",
            purpose="invite",
            expires_at=timezone.now() + timedelta(minutes=30),
        )

        self.api.force_authenticate(user=self.parent)
        denied = self.api.post("/auth/resend-invite", {"user_id": str(user.id)}, format="json")
        self.assertEqual(denied.status_code, 403)

        self.api.force_authenticate(user=self.admin)
        response = self.api.post("/auth/resend-invite", {"user_id": str(user.id)}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("invite_link", response.json())
        self.assertFalse(PasswordResetToken.objects.filter(pk=old.pk).exists())
        self.assertEqual(PasswordResetToken.objects.filter(user=user, purpose="invite", used_at__isnull=True).count(), 1)
        new_token = PasswordResetToken.objects.get(user=user, purpose="invite")
        raw_token = response.json()["invite_link"].split("token=")[-1]
        audit_details = str(list(AuditLog.objects.values("before", "after")))
        self.assertNotIn(raw_token, audit_details)
        self.assertNotIn(new_token.token_hash, audit_details)

    def test_resend_invite_is_limited_to_five_per_minute_per_admin(self):
        self.api.force_authenticate(user=self.admin)
        user = User.objects.create_user(
            username="invite-throttle", password=None, role="operator", school=self.school,
        )
        responses = [
            self.api.post("/auth/resend-invite", {"user_id": str(user.id)}, format="json")
            for _ in range(6)
        ]
        self.assertEqual([response.status_code for response in responses], [200] * 5 + [429])

    def test_admin_user_serializer_exposes_read_only_password_state(self):
        self.assertTrue(UserSerializer(self.parent).data["password_set"])
        self.parent.set_unusable_password()
        self.parent.save(update_fields=["password"])
        self.assertFalse(UserSerializer(self.parent).data["password_set"])

    def test_serializer_redacts_password_bearing_message(self):
        """Defense-in-depth: the API never surfaces a password-looking message."""
        notif = Notification.objects.create(
            recipient=self.parent, title="Reset Password", type="reminder",
            message="Your password was reset successfully. Your new password is Rator#7a.",
        )
        data = NotificationSerializer(notif).data
        self.assertNotIn("Rator#7a", data["message"])
        self.assertNotIn("password", data["message"].lower())


class ThrottlingTests(TestCase):
    """Fix 4: login and forget-password are rate-limited to resist brute force."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Azania Secondary", location="Dar es Salaam")
        cls.user = User.objects.create_user(
            username="throttle1", password="Passw0rd!123", role="parent",
            first_name="T", last_name="User", school=cls.school, email="throttle1@example.com",
        )

    def setUp(self):
        self.api = APIClient()
        # Throttle history is keyed by client IP ('127.0.0.1') in tests and the
        # shared LocMemCache is populated by other test classes, so start each
        # throttle test from a clean cache.
        from django.core.cache import cache
        cache.clear()

    def test_login_throttled_after_burst(self):
        # AllowAny login; wrong creds each time. 5/min budget -> 6th is throttled.
        statuses = []
        for _ in range(6):
            response = self.api.post("/auth/login", {"username": "throttle1", "password": "wrong"}, format="json")
            statuses.append(response.status_code)
        self.assertEqual(statuses[:5], [401] * 5, statuses)
        self.assertEqual(statuses[-1], 429, statuses)

    def test_forget_password_throttled_after_burst(self):
        # 3/min budget -> 4th is throttled.
        statuses = []
        for _ in range(4):
            response = self.api.post("/auth/forgot-password", {"email": "throttle1@example.com"})
            statuses.append(response.status_code)
        self.assertEqual(statuses[:3], [200] * 3, statuses)
        self.assertEqual(statuses[-1], 429, statuses)
