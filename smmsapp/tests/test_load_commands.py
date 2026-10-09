from decimal import Decimal
from io import StringIO

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from smmsapp.models import JournalEntry, JournalLine, PreOrder, RFIDCard, Transaction, TransactionPayment


class LoadCommandTests(TestCase):
    @override_settings(DEBUG=False)
    def test_seeder_refuses_non_debug_settings(self):
        with self.assertRaises(CommandError):
            call_command('seed_load_data', students=2, transactions=3, preorders=0)

    @override_settings(DEBUG=True)
    def test_seeded_small_dataset_balances_wallet_and_preorder_ledgers(self):
        call_command('seed_load_data', students=3, transactions=12, preorders=2, seed=12, verbosity=0)

        self.assertEqual(Transaction.objects.filter(student_or_staff__username__startswith='load-student-').count(), 12)
        self.assertEqual(TransactionPayment.objects.filter(transaction__student_or_staff__username__startswith='load-student-').count(), 12)
        self.assertEqual(PreOrder.objects.filter(idempotency_key__startswith='load-preorder:').count(), 2)
        self.assertEqual(JournalEntry.objects.count(), 3 + 12 + 1 + 4)

        for card in RFIDCard.objects.filter(card_number__startswith='LOAD-CARD-'):
            wallet = JournalLine.objects.filter(rfid_card=card, account__code='2000')
            self.assertEqual(sum((line.amount if line.direction == 'credit' else -line.amount for line in wallet), Decimal('0')), card.balance)
            holds = JournalLine.objects.filter(rfid_card=card, account__code='2100')
            self.assertEqual(sum((line.amount if line.direction == 'credit' else -line.amount for line in holds), Decimal('0')), card.held_balance)

        benchmark = StringIO()
        call_command('benchmark_load_endpoints', iterations=1, stdout=benchmark, verbosity=0)
        self.assertIn('p50_ms', benchmark.getvalue())
        self.assertIn('p95_ms', benchmark.getvalue())
