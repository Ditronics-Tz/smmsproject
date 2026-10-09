from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from smmsapp.models import (
    CanteenItem, FeatureFlag, JournalEntry, JournalLine, LedgerAccount,
    RFIDCard, School, Transaction,
)
from smmsapp.services.features import is_enabled


User = get_user_model()


class LedgerReadScopeAndQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school_a = School.objects.create(name='Ledger scope A')
        cls.school_b = School.objects.create(name='Ledger scope B')
        cls.admin_a = User.objects.create_user(
            username='ledger-admin-a', role='admin', school=cls.school_a,
        )
        student_a = User.objects.create_user(
            username='ledger-student-a', role='student', school=cls.school_a,
        )
        student_b = User.objects.create_user(
            username='ledger-student-b', role='student', school=cls.school_b,
        )
        cls.card_a = RFIDCard.objects.create(
            card_number='LEDGER-SCOPE-A', control_number='LEDGER-SCOPE-CTRL-A', student_or_staff=student_a,
        )
        cls.card_b = RFIDCard.objects.create(
            card_number='LEDGER-SCOPE-B', control_number='LEDGER-SCOPE-CTRL-B', student_or_staff=student_b,
        )
        item = CanteenItem.objects.create(name='Ledger scope meal', price=Decimal('100.00'))
        cls._create_purchase_entry('scope-a', cls.card_a, student_a, item, Decimal('100.00'))
        cls._create_purchase_entry('scope-b', cls.card_b, student_b, item, Decimal('900.00'))

    @classmethod
    def _create_purchase_entry(cls, key, card, student, item, amount):
        txn = Transaction.objects.create(
            student_or_staff=student, rfid_card=card, item=item, amount=amount,
            charged_amount=amount, transaction_status='successful',
        )
        entry = JournalEntry.objects.create(
            event_type='purchase', idempotency_key=f'ledger-scope:{key}',
            ref_transaction=txn,
        )
        JournalLine.objects.create(
            entry=entry, account=LedgerAccount.objects.get(code='2000'), rfid_card=card,
            direction='debit', amount=amount, balance_after=-amount,
        )
        JournalLine.objects.create(
            entry=entry, account=LedgerAccount.objects.get(code='4000'),
            direction='credit', amount=amount,
        )

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(key='LEDGER_UI', defaults={'enabled': True})
        is_enabled('LEDGER_UI')  # warm feature cache outside query-count assertions
        self.api = APIClient()
        self.api.force_authenticate(self.admin_a)

    def test_school_admin_trial_balance_is_scoped_and_aggregated_without_n_plus_one(self):
        with self.assertNumQueries(2):
            response = self.api.get('/api/v1/ledger/trial-balance')

        self.assertEqual(response.status_code, 200, response.data)
        income = next(row for row in response.data['accounts'] if row['account'] == '4000')
        self.assertEqual(income['credit'], '100.00')
        self.assertEqual(income['debit'], '0.00')

    def test_school_admin_journal_and_account_statement_hide_other_schools(self):
        journal = self.api.get('/api/v1/ledger/journal')
        statement = self.api.get('/api/v1/ledger/accounts/4000/statement')

        self.assertEqual(journal.status_code, 200, journal.data)
        self.assertEqual(len(journal.data['results']), 1)
        self.assertTrue(JournalEntry.objects.filter(
            id=journal.data['results'][0]['id'], ref_transaction__rfid_card=self.card_a,
        ).exists())
        self.assertEqual(statement.status_code, 200, statement.data)
        self.assertEqual(len(statement.data['results']), 1)
        self.assertEqual(statement.data['results'][0]['amount'], '100.00')
