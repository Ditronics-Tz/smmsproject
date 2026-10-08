from django.core.management.base import BaseCommand
from django.db import transaction

from smmsapp.models import JournalEntry, RFIDCard
from smmsapp.services.ledger import post_opening


class Command(BaseCommand):
    help = 'Create idempotent opening journal entries for current non-zero card balances.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        cards = RFIDCard.objects.exclude(balance=0).order_by('id')
        count = cards.count()
        if options['dry_run']:
            self.stdout.write(f'Would create opening entries for {count} card(s).')
            return
        created = 0
        for card_id in cards.values_list('id', flat=True).iterator():
            with transaction.atomic():
                card = RFIDCard.objects.select_for_update().get(pk=card_id)
                key = f'opening:{card.id}'
                existed = JournalEntry.objects.filter(idempotency_key=key).exists()
                if not existed and post_opening(card):
                    created += 1
        self.stdout.write(f'Created {created} opening entry/entries; skipped {count - created} zero or previously processed card(s).')
