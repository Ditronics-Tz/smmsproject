from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ..models import (
    School, RFIDCard, CanteenItem, Transaction, ScanSession, ParentStudent, Notification,
)
from ..services.alerts import maybe_alert_low_balance, sweep_low_balances

User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    DEFAULT_BALANCE_THRESHOLD="1000.00",
)
class AlertBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Alert School")
        cls.admin = User.objects.create_user(
            username="admin1", password="Passw0rd!123",
            role="admin", is_staff=True, school=cls.school,
        )
        cls.parent = User.objects.create_user(
            username="parent1", password="Passw0rd!123",
            role="parent", school=cls.school,
        )
        cls.student = User.objects.create_user(
            username="student1", password="Passw0rd!123",
            role="student", school=cls.school, first_name="Asha", last_name="Mzee",
        )
        cls.operator = User.objects.create_user(
            username="operator1", password="Passw0rd!123",
            role="operator", school=cls.school,
        )
        cls.card = RFIDCard.objects.create(
            card_number="CARD-1", control_number="CTRL-1",
            student_or_staff=cls.student, balance=Decimal("5000.00"), is_active=True,
        )
        cls.item = CanteenItem.objects.create(name="Chapati", price=Decimal("1500.00"))
        cls.session = ScanSession.objects.create(operator=cls.operator, type="lunch")
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)


class BalanceThresholdConfigTests(AlertBase):
    def test_get_returns_default_effective_threshold(self):
        api = APIClient()
        api.force_authenticate(user=self.parent)
        response = api.get("/dashboard/balance-threshold")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["effective_threshold"]), Decimal("1000.00"))
        self.assertIsNone(response.data["balance_threshold"])

    def test_put_sets_threshold(self):
        api = APIClient()
        api.force_authenticate(user=self.parent)
        response = api.put("/dashboard/balance-threshold", {"balance_threshold": "4000.00"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["balance_threshold"]), Decimal("4000.00"))
        self.assertEqual(Decimal(response.data["effective_threshold"]), Decimal("4000.00"))

    def test_put_null_resets_to_default(self):
        api = APIClient()
        api.force_authenticate(user=self.parent)
        api.put("/dashboard/balance-threshold", {"balance_threshold": "4000.00"}, format="json")
        response = api.put("/dashboard/balance-threshold", {"balance_threshold": None}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["balance_threshold"])
        self.assertEqual(Decimal(response.data["effective_threshold"]), Decimal("1000.00"))


class ScanHookTests(AlertBase):
    def test_scan_below_threshold_creates_reminder(self):
        # Parent sets threshold above the balance remaining after one purchase.
        self.parent.balance_threshold = Decimal("4000.00")
        self.parent.save(update_fields=["balance_threshold"])

        api = APIClient()
        api.force_authenticate(user=self.operator)
        response = api.post("/sessions/scan-card", {
            "session_id": str(self.session.id),
            "card_number": self.card.card_number,
            "item_id": str(self.item.id),
        })
        self.assertEqual(response.status_code, 201)

        reminder = Notification.objects.filter(type="reminder")
        self.assertEqual(reminder.count(), 1)
        self.assertEqual(reminder.first().recipient, self.parent)
        self.assertIn("below", reminder.first().message)

    def test_no_reminder_when_balance_above_threshold(self):
        api = APIClient()
        api.force_authenticate(user=self.operator)
        response = api.post("/sessions/scan-card", {
            "session_id": str(self.session.id),
            "card_number": self.card.card_number,
            "item_id": str(self.item.id),
        })
        self.assertEqual(response.status_code, 201)
        # Default threshold 1000; balance after = 5000 - 1500 = 3500 > 1000.
        self.assertEqual(Notification.objects.filter(type="reminder").count(), 0)

    def test_dedup_only_one_reminder_per_day(self):
        self.parent.balance_threshold = Decimal("4000.00")
        self.parent.save(update_fields=["balance_threshold"])
        self.card.balance = Decimal("1000.00")  # already below threshold
        self.card.save(update_fields=["balance"])
        self.assertEqual(
            maybe_alert_low_balance(self.card, self.student), 1,
        )
        self.assertEqual(
            maybe_alert_low_balance(self.card, self.student), 0,
        )
        self.assertEqual(Notification.objects.filter(type="reminder").count(), 1)


class SweepTests(AlertBase):
    def test_sweep_raises_reminders_for_low_cards(self):
        self.parent.balance_threshold = Decimal("2000.00")
        self.parent.save(update_fields=["balance_threshold"])
        self.card.balance = Decimal("500.00")
        self.card.save(update_fields=["balance"])

        created = sweep_low_balances()
        self.assertGreaterEqual(created, 1)
        self.assertEqual(Notification.objects.filter(type="reminder").count(), created)

    def test_sweep_skips_card_above_threshold(self):
        self.parent.balance_threshold = Decimal("500.00")
        self.parent.save(update_fields=["balance_threshold"])
        # card balance 5000 >= 500, no alert
        created = sweep_low_balances()
        self.assertEqual(created, 0)
