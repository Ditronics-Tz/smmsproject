import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from smmsapp.models import RFIDCard
from smmsapp.services.cards import normalize_uid


class Command(BaseCommand):
    help = 'Import card_number → uid_hex mappings from a CSV file.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            with open(options['csv_file'], newline='', encoding='utf-8-sig') as source:
                rows = list(csv.DictReader(source))
        except OSError as exc:
            raise CommandError(str(exc))
        if not rows or not {'card_number', 'uid_hex'}.issubset(rows[0]):
            raise CommandError('CSV must contain card_number and uid_hex columns.')

        updates, conflicts = [], []
        staged_uids, staged_cards = set(), set()
        for line, row in enumerate(rows, start=2):
            card_number = (row.get('card_number') or '').strip()
            try:
                uid_hex = normalize_uid(row.get('uid_hex'))
            except ValueError as exc:
                conflicts.append(f'line {line}: invalid UID ({exc})')
                continue
            card = RFIDCard.objects.filter(card_number=card_number).first()
            if not card:
                conflicts.append(f'line {line}: unknown card_number {card_number!r}')
                continue
            owner = RFIDCard.objects.filter(uid_hex=uid_hex).exclude(pk=card.pk).first()
            uid_is_card_number = RFIDCard.objects.filter(card_number=uid_hex).exclude(pk=card.pk).exists()
            if owner or uid_is_card_number or uid_hex in staged_uids or card_number in staged_cards:
                conflicts.append(f'line {line}: UID/card identifier conflict for {card_number!r} → {uid_hex}')
                continue
            if card.uid_hex and card.uid_hex != uid_hex:
                conflicts.append(f'line {line}: {card_number!r} already maps to {card.uid_hex}')
                continue
            staged_uids.add(uid_hex)
            staged_cards.add(card_number)
            updates.append((card, uid_hex))

        if not options['dry_run'] and not conflicts:
            with transaction.atomic():
                for card, uid_hex in updates:
                    card.uid_hex = uid_hex
                    card.save(update_fields=['uid_hex', 'updated_at'])
        self.stdout.write(f"{'Would import' if options['dry_run'] else 'Imported'}: {len(updates)}")
        self.stdout.write(f'Conflicts: {len(conflicts)}')
        for conflict in conflicts:
            self.stdout.write(self.style.WARNING(conflict))
