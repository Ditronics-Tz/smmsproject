from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from decimal import Decimal

from ..models import School, RFIDCard, CanteenItem, Transaction, ScannedData, ScanSession, ReplacementLink, LedgerEntry, ParentStudent

User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class CardReplacementBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Azania Secondary", location="Dar es Salaam")
        cls.admin = User.objects.create_user(
            username="admin1", password="Passw0rd!123", role="admin", is_staff=True,
            first_name="Ada", last_name="Admin", school=cls.school,
        )
        cls.parent = User.objects.create_user(
            username="parent1", password="Passw0rd!123", role="parent",
            first_name="Papa", last_name="Mzee", school=cls.school,
        )
        cls.student = User.objects.create_user(
            username="student1", password="Passw0rd!123", role="student",
            first_name="Asha", last_name="Mzee", school=cls.school,
        )
        cls.operator = User.objects.create_user(
            username="operator1", password="Passw0rd!123", role="operator",
            first_name="Opa", last_name="Rator", school=cls.school,
        )
        cls.card = RFIDCard.objects.create(
            card_number="CARD-0001",
            control_number="CTRL-0001",
            student_or_staff=cls.student,
            balance=Decimal("5000.00"),
            is_active=True,
        )
        cls.item = CanteenItem.objects.create(name="Chapati & Beans", price=Decimal("1500.00"))
        cls.session = ScanSession.objects.create(operator=cls.operator, type="lunch")
        # Seed some history so replacement can be tested repointing it.
        cls.txn = Transaction.objects.create(
            student_or_staff=cls.student, rfid_card=cls.card, item=cls.item,
            amount=Decimal("1500.00"), transaction_status="successful", session=cls.session,
        )
        cls.scanned = ScannedData.objects.create(
            session=cls.session, student_or_staff=cls.student, rfid_card=cls.card, item=cls.item,
        )
        LedgerEntry.objects.create(
            rfid_card=cls.card, event_type='purchase', amount=Decimal("-1500.00"),
            balance_before=Decimal("6500.00"), balance_after=Decimal("5000.00"),
            ref_transaction=cls.txn,
        )

        cls.parent_student = ParentStudent.objects.create(
            parent=cls.parent, student=cls.student,
        )

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)


class ReplaceCardTests(CardReplacementBase):
    def _replace(self, **overrides):
        payload = {
            "old_card_id": str(self.card.id),
            "new_card_number": "CARD-REPLACED-1",
            "reason": "card lost",
            "carry_balance": True,
        }
        payload.update(overrides)
        return self.api.post("/resources/replace-card", payload)

    def test_replacement_creates_new_card_and_deactivates_old(self):
        response = self._replace()
        self.assertEqual(response.status_code, 200, response.content)

        self.card.refresh_from_db()
        self.assertFalse(self.card.is_active)  # old card instantly unusable

        new_card = RFIDCard.objects.get(card_number="CARD-REPLACED-1")
        self.assertTrue(new_card.is_active)
        self.assertEqual(new_card.student_or_staff, self.student)
        self.assertEqual(new_card.balance, Decimal("5000.00"))  # balance carried over

        # Audit link recorded.
        self.assertTrue(ReplacementLink.objects.filter(old_card=self.card, new_card=new_card).exists())

    def test_history_is_repointed_to_new_card(self):
        self._replace()
        new_card = RFIDCard.objects.get(card_number="CARD-REPLACED-1")

        self.assertFalse(Transaction.objects.filter(rfid_card=self.card).exists())
        self.assertTrue(Transaction.objects.filter(rfid_card=new_card).exists())
        self.assertFalse(ScannedData.objects.filter(rfid_card=self.card).exists())
        self.assertTrue(ScannedData.objects.filter(rfid_card=new_card).exists())
        self.assertFalse(LedgerEntry.objects.filter(rfid_card=self.card).exists())
        self.assertTrue(LedgerEntry.objects.filter(rfid_card=new_card).exists())

    def test_replacement_records_card_replacement_ledger_entry(self):
        self._replace()
        new_card = RFIDCard.objects.get(card_number="CARD-REPLACED-1")
        entry = LedgerEntry.objects.filter(rfid_card=new_card, event_type='card_replacement').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.amount, Decimal("5000.00"))

    def test_old_card_cannot_be_scanned_after_replacement(self):
        self._replace()
        # A scan against the deactivated old card must fail (is_active=False).
        operator_api = APIClient()
        operator_api.force_authenticate(user=self.operator)
        scan_response = operator_api.post("/sessions/scan-card", {
            "session_id": str(self.session.id),
            "card_number": self.card.card_number,
            "item_id": str(self.item.id),
        })
        self.assertEqual(scan_response.status_code, 404)

    def test_duplicate_card_number_is_rejected(self):
        response = self._replace(new_card_number=self.card.card_number)
        self.assertEqual(response.status_code, 400)

    def test_replacing_an_inactive_card_is_rejected(self):
        self.card.is_active = False
        self.card.save(update_fields=['is_active'])
        response = self._replace()
        self.assertEqual(response.status_code, 400)

    def test_non_admin_cannot_replace(self):
        from rest_framework.test import APIClient as C
        self.api = C()
        self.api.force_authenticate(user=self.parent)
        response = self._replace()
        self.assertEqual(response.status_code, 403)

    def test_carry_balance_false_starts_new_card_at_zero(self):
        response = self._replace(carry_balance=False)
        self.assertEqual(response.status_code, 200)
        new_card = RFIDCard.objects.get(card_number="CARD-REPLACED-1")
        self.assertEqual(new_card.balance, Decimal("0.00"))
