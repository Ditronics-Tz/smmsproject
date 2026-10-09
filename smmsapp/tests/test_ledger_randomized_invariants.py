"""Deterministic money-operation sequences for the ledger invariants."""
from datetime import date
from decimal import Decimal
import random

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from smmsapp.models import (
    BankDeposit, CanteenItem, RFIDCard, Reversal, School, Transaction,
)
from smmsapp.services.ledger import (
    check_ledger_integrity, post_deposit, post_opening, post_penalty,
    post_purchase, post_replacement, post_reversal,
)


User = get_user_model()


class RandomizedLedgerInvariantTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Randomized ledger invariant school')
        self.admin = User.objects.create_user(
            username='random-ledger-admin', role='admin', school=self.school,
        )
        self.student = User.objects.create_user(
            username='random-ledger-student', role='student', school=self.school,
        )
        self.item = CanteenItem.objects.create(name='Randomized meal', price=Decimal('1250.00'))
        self.card = RFIDCard.objects.create(
            card_number='RANDOM-LEDGER-1', control_number='RANDOM-LEDGER-CN-1',
            student_or_staff=self.student, balance=Decimal('3000.00'),
        )
        with transaction.atomic():
            post_opening(self.card, actor=self.admin)

    def assert_ledger_invariants(self, operation):
        result = check_ledger_integrity(persist=False)
        self.assertTrue(result['global_balanced'], f'{operation}: {result}')
        self.assertEqual(result['mismatched_cards'], [], f'{operation}: {result}')
        self.assertEqual(result['mismatched_funds'], [], f'{operation}: {result}')

    def test_random_200_wallet_operations_keep_ledger_and_card_balances_equal(self):
        rng = random.Random(31031)
        transactions = []
        card_number = 1
        actions = ['deposit', 'purchase', 'penalty', 'reverse', 'replacement'] * 40
        rng.shuffle(actions)

        for index, action in enumerate(actions):
            if action == 'deposit':
                amount = Decimal(rng.choice([500, 1250, 3000, 7500])).quantize(Decimal('0.01'))
                deposit = BankDeposit.objects.create(
                    control_number=self.card, amount=amount, payment_method=rng.choice(['cash', 'mobile_money']),
                    status='processed', processed_at=timezone.now(),
                )
                with transaction.atomic():
                    locked = RFIDCard.objects.select_for_update().get(pk=self.card.pk)
                    locked.balance += amount
                    locked.save(update_fields=['balance'])
                    post_deposit(deposit, actor=self.admin)

            elif action in ('purchase', 'penalty'):
                before = self.card.balance
                assessed = Decimal(rng.choice([500, 1250, 2500, 6000])).quantize(Decimal('0.01'))
                if action == 'purchase' and before < assessed:
                    action = 'penalty'
                if action == 'purchase':
                    after = before - assessed
                    charged = assessed
                    status = 'successful'
                else:
                    from django.conf import settings
                    assessed += Decimal(str(settings.PENALTY_FEE))
                    after = max(before - assessed, Decimal(str(settings.RFID_BALANCE_FLOOR)))
                    charged = before - after
                    status = 'penalty'
                txn = Transaction.objects.create(
                    student_or_staff=self.student, rfid_card=self.card, item=self.item,
                    amount=assessed, charged_amount=charged, transaction_status=status,
                )
                with transaction.atomic():
                    locked = RFIDCard.objects.select_for_update().get(pk=self.card.pk)
                    locked.balance = after
                    locked.save(update_fields=['balance'])
                    if status == 'successful':
                        post_purchase(txn, actor=self.admin)
                    else:
                        post_penalty(txn, actor=self.admin)
                transactions.append(txn)

            elif action == 'reverse':
                reversible = [txn for txn in transactions if not txn.is_voided]
                if reversible:
                    txn = rng.choice(reversible)
                    reversal = Reversal.objects.create(
                        transaction=txn, reversed_by=self.admin, reason=f'Random invariant reversal {index}',
                    )
                    with transaction.atomic():
                        locked = RFIDCard.objects.select_for_update().get(pk=txn.rfid_card_id)
                        locked.balance += txn.charged_amount
                        locked.save(update_fields=['balance'])
                        txn.is_voided = True
                        txn.save(update_fields=['is_voided'])
                        for entry in txn.journal_entries.order_by('created_at', 'id'):
                            post_reversal(entry, reversal, actor=self.admin)

            else:  # transfer the full wallet liability to a replacement card
                previous = self.card
                card_number += 1
                replacement = RFIDCard.objects.create(
                    card_number=f'RANDOM-LEDGER-{card_number}',
                    control_number=f'RANDOM-LEDGER-CN-{card_number}',
                    student_or_staff=self.student, balance=Decimal('0.00'),
                )
                amount = previous.balance
                with transaction.atomic():
                    locked_old = RFIDCard.objects.select_for_update().get(pk=previous.pk)
                    locked_new = RFIDCard.objects.select_for_update().get(pk=replacement.pk)
                    locked_old.balance = Decimal('0.00')
                    locked_new.balance = amount
                    locked_old.save(update_fields=['balance'])
                    locked_new.save(update_fields=['balance'])
                    post_replacement(locked_old, locked_new, amount, actor=self.admin)
                self.card = replacement

            self.card.refresh_from_db()
            self.assert_ledger_invariants(f'{index}: {action}')

