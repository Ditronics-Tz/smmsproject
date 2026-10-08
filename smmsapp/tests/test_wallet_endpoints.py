"""Regression tests for the wallet/ledger endpoints.

These endpoints shipped broken: both serializers raised at instantiation
because declared fields were missing from Meta.fields, and
CardLedgerViewSerializer referenced model attributes that do not exist
(`event_type_display`, `description`). DRF turns the latter into a silently
omitted field (SkipField) or a 500, so nothing caught it.
"""
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from ..models import (
    BankDeposit, CanteenItem, LedgerEntry, ParentStudent, RFIDCard, School,
)

User = get_user_model()


@override_settings(FEATURES_DEFAULT={'PAYMENTS': True, 'LEDGER_UI': True})
class WalletEndpointRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Azania Secondary", location="Dar es Salaam")
        cls.admin = User.objects.create_user(
            username="walletadmin", password="Passw0rd!123", role="admin",
            school=cls.school, first_name="Ada",
        )
        cls.student = User.objects.create_user(
            username="walletstudent", password="Passw0rd!123", role="student",
            school=cls.school, first_name="Zee", last_name="Mushi",
        )
        cls.parent = User.objects.create_user(
            username="walletparent", password="Passw0rd!123", role="parent",
            school=cls.school, first_name="Parent", mobile_number="+255712345123",
        )
        cls.other_parent = User.objects.create_user(
            username="walletparent2", password="Passw0rd!123", role="parent",
            school=cls.school, first_name="Other", mobile_number="+255755555456",
        )
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.item = CanteenItem.objects.create(name="Ugali", price=Decimal("1000.00"))
        cls.card = RFIDCard.objects.create(
            card_number="W-1", student_or_staff=cls.student,
            balance=Decimal("20000.00"), control_number="WCTL1",
        )
        cls.deposit = BankDeposit.objects.create(
            control_number=cls.card, amount=Decimal("20000.00"), status="pending",
            payment_method="mobile_money", provider="M-Pesa", reference="MPESA-123",
            submitted_by=cls.parent,
        )
        cls.other_deposit = BankDeposit.objects.create(
            control_number=cls.card, amount=Decimal("5000.00"), status="pending",
            submitted_by=cls.other_parent,
        )
        cls.entry = LedgerEntry.objects.create(
            rfid_card=cls.card, event_type="deposit", amount=Decimal("20000.00"),
            balance_before=Decimal("0.00"), balance_after=Decimal("20000.00"),
            ref_deposit=cls.deposit,
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)

    def test_deposit_list_exposes_card_and_student_fields(self):
        """BankDeposit's card FK is named control_number, not rfid_card."""
        response = self.api.get("/wallet/deposit/list", {"provider": "M-Pesa"})
        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["card_number"], "W-1")
        self.assertEqual(row["student_name"], "Zee")
        self.assertEqual(row["payment_method"], "mobile_money")
        self.assertEqual(row["provider"], "M-Pesa")
        self.assertEqual(row["reference"], "MPESA-123")
        self.assertEqual(row["phone_masked"], "+255 7** *** 123")
        self.assertNotIn("+255712345123", str(row))

    def test_deposit_filters_payment_provider_and_status(self):
        response = self.api.get("/wallet/deposit/list", {
            "payment_method": "mobile_money", "provider": "M-Pesa", "status": "pending",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["results"]], [str(self.deposit.id)])

    def test_deposit_filters_inclusive_date_range(self):
        response = self.api.get("/wallet/deposit/list", {
            "from": "2000-01-01", "to": "2000-01-02",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_parent_sees_only_own_deposits(self):
        self.api.force_authenticate(user=self.parent)
        response = self.api.get("/wallet/deposit/list")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["results"]], [str(self.deposit.id)])

    def test_card_ledger_renders_display_and_description(self):
        response = self.api.get("/wallet/ledger/card", {"card_number": "W-1"})
        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["event_type"], "deposit")
        self.assertEqual(row["event_type_display"], "Deposit")
        self.assertEqual(row["balance_after"], "20000.00")
        self.assertIn("W-1", row["description"])
