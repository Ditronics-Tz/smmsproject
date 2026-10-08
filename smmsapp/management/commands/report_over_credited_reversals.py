import csv

from django.core.management.base import BaseCommand
from django.db.models import Sum

from smmsapp.models import LedgerEntry, Reversal


class Command(BaseCommand):
    help = 'Report reversals that restored more than the transaction actually charged; does not modify data.'

    def handle(self, *args, **options):
        writer = csv.writer(self.stdout)
        writer.writerow(['reversal_id', 'card_number', 'expected', 'actual', 'difference'])
        rows = 0
        reversals = Reversal.objects.select_related('transaction__rfid_card').order_by('reversed_at')
        for reversal in reversals.iterator():
            transaction = reversal.transaction
            actual = LedgerEntry.objects.filter(
                ref_transaction=transaction, event_type='reversal',
            ).aggregate(total=Sum('amount'))['total'] or 0
            expected = transaction.charged_amount
            if actual > expected:
                writer.writerow([
                    reversal.id, transaction.rfid_card.card_number,
                    f'{expected:.2f}', f'{actual:.2f}', f'{actual - expected:.2f}',
                ])
                rows += 1
        self.stderr.write(f'Reported {rows} over-credited reversal(s).')
