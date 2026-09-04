from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from ..models import School, PasswordResetToken

User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PasswordResetTests(TestCase):
    """Token-based self-service reset replaces plaintext password emailing."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Azania Secondary", location="Dar es Salaam")
        cls.parent = User.objects.create_user(
            username="parent1", password="Passw0rd!123", role="parent",
            first_name="Papa", last_name="Mzee", school=cls.school, email="parent1@example.com",
        )

    def setUp(self):
        super().setUp()
        self.api = APIClient()

    @staticmethod
    def _hash(token):
        import hashlib
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def test_request_generates_token_and_emails_reset_link_not_plaintext(self):
        self.api.post("/auth/forgot-password", {"email": self.parent.email})

        self.assertEqual(len(mail.outbox), 1)
        email_msg = mail.outbox[0].message().as_string()
        # No plaintext password generated or emailed.
        self.assertNotIn("new password is", email_msg)

        # A single live token is stored, hashed (never plaintext).
        token = PasswordResetToken.objects.filter(user=self.parent, used_at__isnull=True).get()
        self.assertNotIn(token.token_hash, email_msg)

    def test_request_is_enumeration_resistant(self):
        # Non-existent email returns the same generic success as a real one.
        missing = self.api.post("/auth/forgot-password", {"email": "nobody@nowhere.com"})
        existing = self.api.post("/auth/forgot-password", {"email": self.parent.email})
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(existing.status_code, 200)
        self.assertEqual(missing.json()["message"], existing.json()["message"])
        # No email should have been sent for the non-existent account.
        self.assertEqual(len(mail.outbox), 1)

    def test_confirm_sets_new_password_and_marks_token_used(self):
        self.api.post("/auth/forgot-password", {"email": self.parent.email})
        raw = mail.outbox[0].body.split("Reset token: ")[1].split("\n")[0]

        response = self.api.post("/auth/reset-password/confirm", {
            "token": raw,
            "new_password": "NewSecure!Pass123",
        })
        self.assertEqual(response.status_code, 200)

        self.parent.refresh_from_db()
        self.assertTrue(self.parent.check_password("NewSecure!Pass123"))
        token = PasswordResetToken.objects.get(user=self.parent)
        self.assertIsNotNone(token.used_at)

    def test_token_is_single_use(self):
        self.api.post("/auth/forgot-password", {"email": self.parent.email})
        raw = mail.outbox[0].body.split("Reset token: ")[1].split("\n")[0]

        first = self.api.post("/auth/reset-password/confirm", {"token": raw, "new_password": "NewSecure!Pass123"})
        self.assertEqual(first.status_code, 200)

        second = self.api.post("/auth/reset-password/confirm", {"token": raw, "new_password": "AnotherPass456"})
        self.assertEqual(second.status_code, 400)
        # Password remains the first one.
        self.parent.refresh_from_db()
        self.assertTrue(self.parent.check_password("NewSecure!Pass123"))

    def test_expired_token_is_rejected(self):
        self.api.post("/auth/forgot-password", {"email": self.parent.email})
        raw = mail.outbox[0].body.split("Reset token: ")[1].split("\n")[0]
        token = PasswordResetToken.objects.get(user=self.parent)
        token.expires_at = timezone.now() - timedelta(minutes=1)
        token.save(update_fields=['expires_at'])

        response = self.api.post("/auth/reset-password/confirm", {"token": raw, "new_password": "NewSecure!Pass123"})
        self.assertEqual(response.status_code, 400)
        self.parent.refresh_from_db()
        self.assertFalse(self.parent.check_password("NewSecure!Pass123"))

    def test_invalid_token_is_rejected(self):
        response = self.api.post("/auth/reset-password/confirm", {
            "token": "not-a-real-token",
            "new_password": "NewSecure!Pass123",
        })
        self.assertEqual(response.status_code, 400)
