"""Regression tests for the Phase 6 typo / logic fixes.

1. ``sessions.py`` scan-card penalty branch compared ``role == 'stundent'``,
   a typo that never matched, so parents were sent the self-service penalty
   message instead of the child-specific one.
2. ``sessions.py`` blocked-card branch used ``title:`` (a PEP 526 annotation)
   instead of ``title =``, leaving the title unassigned.
3. The penalty ``transaction_status`` was stored as the misspelled value
   ``'penalt'`` instead of ``'penalty'``.
4. The admin/card-details deny responses used the typo'd key ``"messsage"``
   instead of the ``"message"`` used everywhere else.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ..models import (
    CanteenItem,
    Notification,
    ParentStudent,
    RFIDCard,
    ScanSession,
    ScannedData,
    School,
    Transaction,
)
User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class Phase6ScanCardBase(TestCase):
    """Shared fixtures for the scan-card penalty flow."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Phase6 School", location="Dar es Salaam")

        cls.admin = User.objects.create_user(
            username="p6admin", password="Passw0rd!123", role="admin", is_staff=True,
            school=cls.school,
        )
        cls.parent = User.objects.create_user(
            username="p6parent", password="Passw0rd!123", role="parent", school=cls.school,
        )
        cls.student = User.objects.create_user(
            username="p6student", password="Passw0rd!123", role="student",
            first_name="Zawadi", last_name="Kidawa", school=cls.school,
        )
        cls.operator = User.objects.create_user(
            username="p6operator", password="Passw0rd!123", role="operator", school=cls.school,
        )

        cls.card = RFIDCard.objects.create(
            card_number="P6-0001",
            control_number="P6CTRL-0001",
            student_or_staff=cls.student,
            balance=Decimal("0.00"),
        )
        cls.item = CanteenItem.objects.create(name="Rice & Beef", price=Decimal("2000.00"))
        cls.session = ScanSession.objects.create(operator=cls.operator, type="lunch", status="active")
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(user=self.operator)

    def _scan(self):
        payload = {
            "session_id": str(self.session.id),
            "card_number": self.card.card_number,
            "item_id": str(self.item.id),
        }
        return self.api.post("/sessions/scan-card", payload)


class ScanCardPenaltyStatusTests(Phase6ScanCardBase):
    """The penalty transaction is stored as the corrected value 'penalty'."""

    def test_insufficient_balance_stores_penalty_status(self):
        # Student has 0 balance, item costs 2000 -> penalty branch.
        response = self._scan()
        self.assertEqual(response.status_code, 201, response.data)

        transaction = Transaction.objects.get(student_or_staff=self.student)
        self.assertEqual(transaction.transaction_status, "penalty")

    def test_sufficient_balance_stores_successful_status(self):
        self.card.balance = Decimal("5000.00")
        self.card.save()

        response = self._scan()
        self.assertEqual(response.status_code, 201, response.data)

        transaction = Transaction.objects.get(student_or_staff=self.student)
        self.assertEqual(transaction.transaction_status, "successful")


class ScanCardParentNotificationTests(Phase6ScanCardBase):
    """Parents receive the child-specific penalty message (the 'stundent' fix)."""

    def setUp(self):
        super().setUp()

    def test_parent_gets_child_specific_penalty_message(self):
        response = self._scan()
        self.assertEqual(response.status_code, 201, response.data)

        notification = Notification.objects.filter(recipient=self.parent).latest("id")
        self.assertIn("Your child Zawadi", notification.message)

    def test_student_with_sufficient_balance_also_notifies_parent(self):
        self.card.balance = Decimal("5000.00")
        self.card.save()

        response = self._scan()
        self.assertEqual(response.status_code, 201, response.data)

        notification = Notification.objects.filter(recipient=self.parent).latest("id")
        self.assertIn("Your child Zawadi", notification.message)


class DenyResponseMessageKeyTests(Phase6ScanCardBase):
    """Deny responses use the correct 'message' key, not the 'messsage' typo.

    AdminDetailsView is gated by DRF's IsAdminUser (is_staff), so a staff
    member whose role is not 'admin' passes the permission gate and reaches
    the view body that builds the deny response.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.staff_non_admin = User.objects.create_user(
            username="p6staff", password="Passw0rd!123", role="staff",
            is_staff=True, school=cls.school,
        )

    def test_admin_details_deny_uses_message_key(self):
        self.api.force_authenticate(user=self.staff_non_admin)
        response = self.api.post("/resources/admin-details", {})
        self.assertEqual(response.status_code, 403)
        self.assertIn("message", response.data)
        self.assertNotIn("messsage", response.data)
