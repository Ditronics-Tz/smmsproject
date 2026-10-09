from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from smmsapp.models import (
    JournalEntry, JournalLine, LedgerAccount, ParentStudent, RFIDCard, School,
)
from smmsapp.services.ledger_reads import statement_period


User = get_user_model()


@override_settings(FEATURES_DEFAULT={"LEDGER_UI": True})
class ParentWalletStatementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Statement School", location="Dodoma")
        cls.student = User.objects.create_user(
            username="statement-student", password="Passw0rd!123", role="student",
            first_name="Asha", last_name="Mushi", school=cls.school,
        )
        cls.parent = User.objects.create_user(
            username="statement-parent", password="Passw0rd!123", role="parent", school=cls.school,
        )
        cls.other_parent = User.objects.create_user(
            username="statement-other", password="Passw0rd!123", role="parent", school=cls.school,
        )
        cls.admin = User.objects.create_user(
            username="statement-admin", password="Passw0rd!123", role="admin",
            is_staff=True, school=cls.school,
        )
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.card = RFIDCard.objects.create(
            card_number="STMT-1", control_number="STMT-CN-1", student_or_staff=cls.student,
            balance=Decimal("750.00"), held_balance=Decimal("150.00"),
        )

    def setUp(self):
        self.api = APIClient()
        self.start = timezone.localdate()
        self.end = self.start
        self._create_entry("opening-statement", "opening", [
            ("3000", "debit", "1000.00", None),
            ("2000", "credit", "1000.00", self.card),
            ("3000", "debit", "100.00", None),
            ("2100", "credit", "100.00", self.card),
        ], created_at=timezone.now() - timedelta(days=2))
        self._create_entry("statement-events", "activity", [
            ("2000", "debit", "200.00", self.card),
            ("4000", "credit", "200.00", None),
        ], created_at=timezone.now() - timedelta(hours=2))
        self._create_entry("statement-hold", "preorder_hold", [
            ("2000", "debit", "50.00", self.card),
            ("2100", "credit", "50.00", self.card),
        ], created_at=timezone.now() - timedelta(hours=1))

    def _create_entry(self, key, event, lines, created_at):
        entry = JournalEntry.objects.create(event_type=event, idempotency_key=key, memo="Test <entry>")
        JournalEntry.objects.filter(pk=entry.pk).update(created_at=created_at)
        for code, direction, amount, card in lines:
            JournalLine.objects.create(
                entry=entry, account=LedgerAccount.objects.get(code=code), rfid_card=card,
                direction=direction, amount=Decimal(amount),
            )
        JournalLine.objects.filter(entry=entry).update(created_at=created_at)

    def _path(self, child_id=None, date_from=None, date_to=None):
        return "/wallet/statement.pdf?child_id={}&from={}&to={}".format(
            child_id or self.student.id, date_from or self.start.isoformat(), date_to or self.end.isoformat(),
        )

    def test_statement_totals_come_from_wallet_and_hold_journal_lines(self):
        values = statement_period(self.card, self.start, self.end)
        self.assertEqual(values["opening_balance"], Decimal("1000.00"))
        self.assertEqual(values["closing_balance"], Decimal("750.00"))
        self.assertEqual(values["opening_held_balance"], Decimal("100.00"))
        self.assertEqual(values["closing_held_balance"], Decimal("150.00"))
        self.assertEqual(len(values["lines"]), 3)

    @patch("smmsapp.utils._html_to_pdf", return_value=b"%PDF-test")
    def test_parent_gets_pdf_and_personal_data_is_html_escaped(self, pdf_render):
        self.api.force_authenticate(user=self.parent)
        response = self.api.get(self._path())
        self.assertEqual(response.status_code, 200, getattr(response, "data", None))
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertEqual(response.content, b"%PDF-test")
        html = pdf_render.call_args.args[0]
        self.assertIn("Opening wallet balance: TZS 1000.00", html)
        self.assertIn("Closing wallet balance: TZS 750.00", html)
        self.assertIn("Test &lt;entry&gt;", html)

    def test_parent_cannot_view_an_unlinked_child_statement(self):
        self.api.force_authenticate(user=self.other_parent)
        response = self.api.get(self._path())
        self.assertEqual(response.status_code, 403)

    def test_admin_is_limited_to_own_school(self):
        foreign_school = School.objects.create(name="Foreign statement school")
        foreign_child = User.objects.create_user(
            username="foreign-child", password="Passw0rd!123", role="student", school=foreign_school,
        )
        self.api.force_authenticate(user=self.admin)
        response = self.api.get(self._path(child_id=foreign_child.id))
        self.assertEqual(response.status_code, 404)

    def test_date_range_and_format_are_validated(self):
        self.api.force_authenticate(user=self.parent)
        invalid_format = self.api.get(self._path(date_from="not-a-date"))
        self.assertEqual(invalid_format.status_code, 400)
        too_long = self.api.get(self._path(date_from="2024-01-01", date_to="2025-01-02"))
        self.assertEqual(too_long.status_code, 400)
