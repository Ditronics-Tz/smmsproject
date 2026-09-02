import csv
from io import StringIO
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ..models import (
    School, RFIDCard, CanteenItem, Transaction, ScanSession, ParentStudent,
    Notification, BankDeposit,
)
from ..views.exports import _make_token, _read_token, _storage_dir

User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EXPORT_SYNC_MAX_ROWS=2000,
)
class ExportBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school_a = School.objects.create(name="School A")
        cls.school_b = School.objects.create(name="School B")

        cls.admin_global = User.objects.create_user(
            username="globaladmin", password="Passw0rd!123", role="admin", is_staff=True,
        )
        cls.admin_a = User.objects.create_user(
            username="admina", password="Passw0rd!123", role="admin", is_staff=True,
            school=cls.school_a,
        )
        cls.parent = User.objects.create_user(
            username="parent1", password="Passw0rd!123", role="parent", school=cls.school_a,
        )
        cls.student_a = User.objects.create_user(
            username="studenta", password="Passw0rd!123", role="student",
            school=cls.school_a, first_name="Asha", last_name="A",
        )
        cls.student_b = User.objects.create_user(
            username="studentb", password="Passw0rd!123", role="student",
            school=cls.school_b, first_name="Bora", last_name="B",
        )
        cls.operator = User.objects.create_user(
            username="op1", password="Passw0rd!123", role="operator", school=cls.school_a,
        )
        cls.card_a = RFIDCard.objects.create(
            card_number="CARD-A", control_number="CTRL-A",
            student_or_staff=cls.student_a, balance=Decimal("5000.00"), is_active=True,
        )
        cls.card_b = RFIDCard.objects.create(
            card_number="CARD-B", control_number="CTRL-B",
            student_or_staff=cls.student_b, balance=Decimal("9000.00"), is_active=True,
        )
        cls.item = CanteenItem.objects.create(name="Chapati", price=Decimal("1500.00"))
        cls.session = ScanSession.objects.create(operator=cls.operator, type="lunch")

        cls.txn_a = Transaction.objects.create(
            student_or_staff=cls.student_a, rfid_card=cls.card_a, item=cls.item,
            amount=Decimal("1500.00"), transaction_status="successful", session=cls.session,
        )
        cls.txn_b = Transaction.objects.create(
            student_or_staff=cls.student_b, rfid_card=cls.card_b, item=cls.item,
            amount=Decimal("1500.00"), transaction_status="successful", session=cls.session,
        )

        ParentStudent.objects.create(parent=cls.parent, student=cls.student_a)

        cls.deposit_a = BankDeposit.objects.create(
            control_number=cls.card_a, amount=Decimal("1000.00"),
            status="pending", submitted_by=cls.parent,
        )
        cls.deposit_other = BankDeposit.objects.create(
            control_number=cls.card_b, amount=Decimal("2000.00"),
            status="processed", submitted_by=None,
        )

    def _client(self, user):
        api = APIClient()
        api.force_authenticate(user=user)
        return api


class TransactionExportTests(ExportBase):
    def test_sync_csv_returns_attachment(self):
        response = self._client(self.admin_global).post("/exports/transactions", {"export_format": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"].split(";")[0], "attachment")
        self.assertIn("text/csv", response["Content-Type"])

    def test_parent_export_limited_to_own_children(self):
        response = self._client(self.parent).post("/exports/transactions", {"export_format": "csv"})
        content = response.content.decode("utf-8-sig")
        reader = list(csv.reader(StringIO(content)))
        self.assertEqual(reader[0][0], "Transaction ID")
        # Only student A's transaction present, not student B's.
        data_rows = [r for r in reader[1:] if r]
        self.assertEqual(len(data_rows), 1)
        self.assertIn(self.txn_a.id.hex, data_rows[0][0])

    def test_school_admin_export_scoped(self):
        response = self._client(self.admin_a).post("/exports/transactions", {"export_format": "csv"})
        content = response.content.decode("utf-8-sig")
        data_rows = [r for r in list(csv.reader(StringIO(content)))[1:] if r]
        self.assertEqual(len(data_rows), 1)
        self.assertIn(self.txn_a.id.hex, data_rows[0][0])


class StudentExportTests(ExportBase):
    def test_school_admin_students_scoped(self):
        response = self._client(self.admin_a).post("/exports/students", {"export_format": "csv"})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8-sig")
        reader = list(csv.reader(StringIO(content)))
        usernames = [row[0] for row in reader[1:] if row]
        self.assertEqual(usernames, ["studenta"])


class DepositExportTests(ExportBase):
    def test_parent_sees_only_own_deposits(self):
        response = self._client(self.parent).post("/exports/deposits", {"export_format": "csv"})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8-sig")
        reader = list(csv.reader(StringIO(content)))
        # only deposit_a (submitted_by=parent); deposit_other not included
        card_numbers = [row[0] for row in reader[1:] if row]
        self.assertEqual(card_numbers, ["CARD-A"])


class AsyncExportTests(ExportBase):
    @patch("smmsapp.tasks.generate_export_task.delay")
    def test_async_returns_token_and_notifies(self, mock_delay):
        response = self._client(self.admin_global).post(
            "/exports/transactions", {"export_format": "csv", "async_mode": True}
        )
        self.assertEqual(response.status_code, 202)
        self.assertIn("token", response.data)
        self.assertTrue(mock_delay.called)
        self.assertIsNotNone(Notification.objects.filter(title="Export Requested").first())

    def test_token_roundtrip(self):
        token = _make_token("transactions", "transactions-abc.csv", self.admin_global.id)
        payload = _read_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["entity"], "transactions")
        self.assertEqual(payload["file"], "transactions-abc.csv")
        self.assertEqual(payload["uid"], str(self.admin_global.id))

    def test_invalid_token_rejected(self):
        self.assertIsNone(_read_token("not-a-token"))
