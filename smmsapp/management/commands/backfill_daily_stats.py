from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from smmsapp.services.analytics import build_daily_stats_for_day


class Command(BaseCommand):
    help = 'Build or refresh daily analytics snapshots for an inclusive date range.'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='from_date', required=True, help='Start date (YYYY-MM-DD)')
        parser.add_argument('--to', dest='to_date', required=True, help='End date (YYYY-MM-DD)')

    def handle(self, *args, **options):
        try:
            start = date.fromisoformat(options['from_date'])
            end = date.fromisoformat(options['to_date'])
        except ValueError as exc:
            raise CommandError('Dates must use YYYY-MM-DD format.') from exc
        if start > end:
            raise CommandError('--from must be on or before --to.')

        current = start
        days = snapshots = 0
        while current <= end:
            snapshots += build_daily_stats_for_day(current)
            days += 1
            current += timedelta(days=1)
        self.stdout.write(self.style.SUCCESS(f'Rebuilt {snapshots} snapshots across {days} day(s).'))
