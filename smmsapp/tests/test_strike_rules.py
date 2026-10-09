from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from smmsapp.models import (
    AuditLog, BankDeposit, CanteenItem, ParentStudent, RFIDCard, School, Transaction,
)


User = get_user_model()


@override_settings(FEATURES_DEFAULT={"PAYMENTS": True, "MENU": True})
class StrikeCounterRulesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Strike School", location="Moshi")
        cls.admin = User.objects.create_user(
            username="strike-admin", password="Passw0rd!123", role="admin",
            is_staff=True, school=cls.school,
        )
        cls.operator = User.objects.create_user(
            username="strike-operator", password="Passw0rd!123", role="operator", school=cls.school,
        )
        cls.parent = User.objects.create_user(
            username="strike-parent", password="Passw0rd!123", role="parent", school=cls.school,
        )
        cls.staff = User.objects.create_user(
            username="strike-staff", password="Passw0rd!123", role="staff", school=cls.school,
        )
        cls.student = User.objects.create_user(
            username="strike-student", password="Passw0rd!123", role="student",
            first_name="Asha", last_name="Mushi", school=cls.school,
        )
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.card = RFIDCard.objects.create(
            card_number="STRIKE-1", control_number="STRIKE-CN-1", student_or_staff=cls.student,
            balance=Decimal("0.00"), insufficient_meal_count=2,
        )
        cls.item = CanteenItem.objects.create(name="Tea", price=Decimal("100.00"))

    def setUp(self):
        self.api = APIClient()

    def test_admin_reset_sets_counter_and_audits_before_after_and_reason(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post("/api/v1/resources/reset-strikes", {
            "card_id": str(self.card.id), "reason": "Parent confirmed repayment",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["insufficient_meal_count"], 0)
        self.assertEqual(response.data["strike_limit"], 10)
        row = AuditLog.objects.get(action="update", object_id=str(self.card.id))
        self.assertEqual(row.before["insufficient_meal_count"], "2")
        self.assertEqual(row.after["insufficient_meal_count"], "0")
        self.assertEqual(row.after["reset_reason"], "Parent confirmed repayment")

    def test_only_admin_can_reset_strikes(self):
        for user in (self.operator, self.parent, self.staff, self.student):
            self.api.force_authenticate(user=user)
            with self.subTest(role=user.role):
                response = self.api.post("/api/v1/resources/reset-strikes", {
                    "card_id": str(self.card.id), "reason": "not authorized",
                }, format="json")
                self.assertEqual(response.status_code, 403)

    def test_reset_requires_a_reason(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post("/api/v1/resources/reset-strikes", {"card_id": str(self.card.id)}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_card_and_student_details_include_strike_fields(self):
        self.api.force_authenticate(user=self.admin)
        card_response = self.api.post("/api/v1/resources/card-details", {"card_id": str(self.card.id)}, format="json")
        self.assertEqual(card_response.status_code, 200)
        self.assertEqual(card_response.data["insufficient_meal_count"], 2)
        self.assertEqual(card_response.data["strike_limit"], 10)
        student_response = self.api.post("/api/v1/resources/student-details", {"student_id": str(self.student.id)}, format="json")
        self.assertEqual(student_response.status_code, 200)
        self.assertEqual(student_response.data["insufficient_meal_count"], 2)
        self.assertEqual(student_response.data["rfid_card"]["strike_limit"], 10)

    def test_penalty_reversal_decrements_once_and_normal_reversal_does_not(self):
        self.api.force_authenticate(user=self.admin)
        penalty = Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal("600.00"), charged_amount=Decimal("100.00"),
            transaction_status="penalty",
        )
        response = self.api.post("/api/v1/wallet/transaction/reverse", {
            "transaction_id": str(penalty.id), "reason": "Incorrect penalty",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.card.refresh_from_db()
        self.assertEqual(self.card.insufficient_meal_count, 1)

        normal = Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal("100.00"), charged_amount=Decimal("100.00"),
            transaction_status="successful",
        )
        response = self.api.post("/api/v1/wallet/transaction/reverse", {
            "transaction_id": str(normal.id), "reason": "Duplicate purchase",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.card.refresh_from_db()
        self.assertEqual(self.card.insufficient_meal_count, 1)

    def test_penalty_reversal_never_decrements_below_zero(self):
        self.card.insufficient_meal_count = 0
        self.card.save(update_fields=["insufficient_meal_count"])
        txn = Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal("600.00"), charged_amount=Decimal("100.00"),
            transaction_status="penalty",
        )
        self.api.force_authenticate(user=self.admin)
        response = self.api.post("/api/v1/wallet/transaction/reverse", {
            "transaction_id": str(txn.id), "reason": "Counter floor check",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.card.refresh_from_db()
        self.assertEqual(self.card.insufficient_meal_count, 0)

    def test_deposit_resets_strikes_only_when_setting_is_enabled(self):
        for should_reset in (False, True):
            with self.subTest(should_reset=should_reset), override_settings(STRIKE_RESET_ON_DEPOSIT=should_reset):
                self.card.insufficient_meal_count = 2
                self.card.balance = Decimal("0.00")
                self.card.save(update_fields=["insufficient_meal_count", "balance"])
                deposit = BankDeposit.objects.create(
                    control_number=self.card, amount=Decimal("50.00"), status="pending",
                )
                self.api.force_authenticate(user=self.admin)
                response = self.api.post("/api/v1/wallet/deposit/process", {
                    "deposit_id": str(deposit.id), "action": "process",
                }, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                self.card.refresh_from_db()
                self.assertEqual(self.card.insufficient_meal_count, 0 if should_reset else 2)
