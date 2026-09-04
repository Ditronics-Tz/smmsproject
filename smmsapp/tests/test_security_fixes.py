from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ..models import Notification, School
from ..serializers.resources import NotificationSerializer

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

    def test_create_non_student_stores_sanitized_notification(self):
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
        notification = Notification.objects.filter(recipient=user, title="Login Credentials").latest("id")
        # Sanitized message — no plaintext password stored.
        self.assertEqual(
            notification.message,
            f"Hello Opa, your account was created successfully. Credentials were sent to your email.",
        )
        self.assertNotIn(user.password, notification.message)

        # A credentials email was dispatched with the plaintext password.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Username: opa1", mail.outbox[0].body)

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
