import json
import math
import statistics
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from smmsapp.models import CustomUser, FeatureFlag, RFIDCard, SponsorFund
from smmsapp.services.features import clear_feature_cache


class Command(BaseCommand):
    help = 'Measure analytics, ledger and insights APIs using Django test client (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument('--iterations', type=int, default=20)
        parser.add_argument('--output', default='')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('benchmark_load_endpoints is disabled unless DEBUG=True.')
        if options['iterations'] < 1:
            raise CommandError('--iterations must be at least one.')
        if not CustomUser.objects.filter(username__startswith='load-student-').exists():
            raise CommandError('Run seed_load_data before benchmarking.')
        school = CustomUser.objects.filter(username__startswith='load-student-').values_list('school_id', flat=True).first()
        admin, _ = CustomUser.objects.get_or_create(
            username='load-admin', defaults={'role': 'admin', 'school_id': school, 'is_active': True},
        )
        if admin.role != 'admin':
            raise CommandError('load-admin exists but is not an admin; refusing to change it.')
        FeatureFlag.objects.filter(key__in=['ANALYTICS', 'LEDGER_UI', 'INSIGHTS']).update(enabled=True)
        clear_feature_cache()
        card = RFIDCard.objects.filter(card_number__startswith='LOAD-CARD-').first()
        fund = SponsorFund.objects.filter(name='Synthetic Load Sponsor Fund').first()
        day = timezone.localdate().isoformat()
        endpoints = {
            'analytics_sales': f'/api/v1/analytics/sales?from={day}&to={day}',
            'analytics_wallet_health': '/api/v1/analytics/wallet-health',
            'analytics_operators': f'/api/v1/analytics/operators?from={day}&to={day}',
            'analytics_classes': f'/api/v1/analytics/classes?from={day}&to={day}',
            'analytics_penalties': f'/api/v1/analytics/penalties?from={day}&to={day}',
            'ledger_journal': '/api/v1/ledger/journal',
            'ledger_trial_balance': '/api/v1/ledger/trial-balance',
            'ledger_card_statement': f'/api/v1/ledger/cards/{card.pk}/statement',
            'ledger_fund_statement': f'/api/v1/ledger/funds/{fund.pk}/statement',
            'insights_forecast': f'/api/v1/insights/forecast?date={day}',
            'insights_at_risk': '/api/v1/insights/at-risk',
            'insights_anomalies': '/api/v1/insights/anomalies',
            'insights_dormant_cards': '/api/v1/insights/dormant-cards',
        }
        client = Client()
        token = RefreshToken.for_user(admin).access_token
        client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        results = {}
        for name, path in endpoints.items():
            samples = []
            statuses = []
            for _ in range(options['iterations']):
                started = time.perf_counter()
                response = client.get(path)
                samples.append((time.perf_counter() - started) * 1000)
                statuses.append(response.status_code)
            if any(status < 200 or status >= 300 for status in statuses):
                raise CommandError(f'{name} returned HTTP {sorted(set(statuses))}; benchmark requires successful API responses.')
            ordered = sorted(samples)
            results[name] = {
                'p50_ms': round(statistics.median(ordered), 2),
                'p95_ms': round(ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)], 2),
                'statuses': sorted(set(statuses)),
                'iterations': len(samples),
            }
        output = json.dumps(results, indent=2)
        if options['output']:
            with open(options['output'], 'w', encoding='utf-8') as stream:
                stream.write(output + '\n')
        self.stdout.write(output)
