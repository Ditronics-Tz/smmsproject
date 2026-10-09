from datetime import date
from decimal import Decimal
import random

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum
from django.test import TestCase
from django.utils import timezone

from smmsapp.models import (
    CanteenItem, FundContribution, RFIDCard, School, SponsorFund, Transaction,
    Reversal, TransactionPayment,
)
from smmsapp.services.ledger import LedgerPostingError, check_ledger_integrity, post_fund_contribution, post_fund_spend, post_reversal

User = get_user_model()


class SponsorshipLedgerTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Sponsor Ledger School')
        self.admin = User.objects.create_user(username='sponsor-ledger-admin', role='admin', school=self.school)
        self.student = User.objects.create_user(username='sponsor-ledger-student', role='student', school=self.school)
        self.card = RFIDCard.objects.create(
            card_number='SPONSOR-CARD', control_number='SPONSOR-CTRL',
            student_or_staff=self.student, balance=Decimal('0.00'),
        )
        self.item = CanteenItem.objects.create(name='Sponsored Meal', price=Decimal('100.00'))
        self.fund = SponsorFund.objects.create(
            name='Lunch Bursary', sponsor_name='Community Partner', start_date=date.today(), created_by=self.admin,
        )

    def contribute(self, amount='500.00'):
        contribution = FundContribution.objects.create(
            fund=self.fund, amount=Decimal(amount), method='bank', reference='BANK-REF',
            received_at=timezone.now(), recorded_by=self.admin,
        )
        with transaction.atomic():
            entry = post_fund_contribution(contribution, actor=self.admin)
        return contribution, entry

    def test_contribution_and_spend_balance_and_track_fund_liability(self):
        contribution, contribution_entry = self.contribute()
        self.assertEqual(contribution_entry.lines.count(), 2)
        contribution.refresh_from_db()
        self.assertEqual(contribution.journal_entry, contribution_entry)

        txn = Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal('100.00'), charged_amount=Decimal('0.00'), transaction_status='successful',
        )
        with transaction.atomic():
            spend_entry = post_fund_spend(txn, self.fund, Decimal('125.00'), actor=self.admin)
        fund_line = spend_entry.lines.get(account__code='2200')
        self.assertEqual(fund_line.fund, self.fund)
        self.assertEqual(fund_line.balance_after, Decimal('375.00'))
        self.assertTrue(check_ledger_integrity(persist=False)['global_balanced'])
        self.assertEqual(check_ledger_integrity(persist=False)['mismatched_funds'], [])

    def test_fund_cannot_be_spent_below_zero(self):
        self.contribute('50.00')
        txn = Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal('100.00'), charged_amount=Decimal('0.00'), transaction_status='successful',
        )
        with self.assertRaises(LedgerPostingError):
            with transaction.atomic():
                post_fund_spend(txn, self.fund, Decimal('51.00'), actor=self.admin)

    def test_seeded_random_200_fund_operations_preserve_ledger_invariants(self):
        rng = random.Random(163)
        live = []
        balance = Decimal('0.00')
        for index in range(200):
            action = rng.choice(['contribute', 'contribute', 'scan', 'reverse'])
            if action == 'contribute' or balance < Decimal('100.00'):
                contribution = FundContribution.objects.create(
                    fund=self.fund, amount=Decimal('250.00'), method='cash',
                    reference=f'RANDOM-{index}', received_at=timezone.now(), recorded_by=self.admin,
                )
                with transaction.atomic():
                    post_fund_contribution(contribution, actor=self.admin)
                balance += Decimal('250.00')
            elif action == 'scan':
                txn = Transaction.objects.create(
                    student_or_staff=self.student, rfid_card=self.card, item=self.item,
                    amount=self.item.price, charged_amount=Decimal('0.00'), transaction_status='successful',
                )
                with transaction.atomic():
                    entry = post_fund_spend(txn, self.fund, self.item.price, actor=self.admin)
                    TransactionPayment.objects.create(
                        transaction=txn, source='fund', fund=self.fund,
                        amount=self.item.price, journal_entry=entry,
                    )
                live.append(txn)
                balance -= self.item.price
            elif live:
                txn = live.pop(rng.randrange(len(live)))
                reversal = Reversal.objects.create(transaction=txn, reversed_by=self.admin, reason='Random invariant test')
                txn.is_voided = True
                txn.save(update_fields=['is_voided'])
                with transaction.atomic():
                    for entry in txn.journal_entries.order_by('created_at', 'id'):
                        post_reversal(entry, reversal, actor=self.admin)
                balance += self.item.price

        result = check_ledger_integrity(persist=False)
        self.assertTrue(result['global_balanced'], result)
        self.assertEqual(result['mismatched_funds'], [])
        self.assertEqual(balance, self.fund.journal_lines.filter(account__code='2200').aggregate(
            credits=Sum('amount', filter=Q(direction='credit')),
            debits=Sum('amount', filter=Q(direction='debit')),
        )['credits'] - self.fund.journal_lines.filter(account__code='2200').aggregate(
            credits=Sum('amount', filter=Q(direction='credit')),
            debits=Sum('amount', filter=Q(direction='debit')),
        )['debits'])
        for txn in Transaction.objects.filter(is_voided=False):
            total = sum(txn.payment_parts.values_list('amount', flat=True), Decimal('0.00'))
            self.assertEqual(total, txn.amount)
