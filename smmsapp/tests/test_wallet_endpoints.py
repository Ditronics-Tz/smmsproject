"""Regression tests for the wallet/ledger endpoints.

These endpoints shipped broken: both serializers raised at instantiation
because declared fields were missing from Meta.fields, and
CardLedgerViewSerializer referenced model attributes that do not exist
(`event_type_display`, `description`). DRF turns the latter into a silently
omitted field (SkipField) or a 500, so nothing caught it.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from ..models import (
    BankDeposit, CanteenItem, LedgerEntry, RFIDCard, School,
)

User = get_user_model()


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
        cls.item = CanteenItem.objects.create(name="Ugali", price=Decimal("1000.00"))
        cls.card = RFIDCard.objects.create(
            card_number="W-1", student_or_staff=cls.student,
            balance=Decimal("20000.00"), control_number="WCTL1",
        )
        cls.deposit = BankDeposit.objects.create(
            control_number=cls.card, amount=Decimal("20000.00"), status="pending",
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
        response = self.api.get("/wallet/deposit/list")
        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["card_number"], "W-1")
        self.assertEqual(row["student_name"], "Zee")

    def test_card_ledger_renders_display_and_description(self):
        response = self.api.get("/wallet/ledger/card", {"card_number": "W-1"})
        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["event_type"], "deposit")
        self.assertEqual(row["event_type_display"], "Deposit")
        self.assertEqual(row["balance_after"], "20000.00")
        self.assertIn("W-1", row["description"])
