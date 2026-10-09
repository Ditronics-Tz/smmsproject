from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from smmsapp.models import (
    CanteenItem, FeatureFlag, FundContribution, RFIDCard, ScanSession,
    School, SponsorFund, SponsorshipAllocation, TransactionPayment,
)
from smmsapp.services.ledger import post_fund_contribution
from django.db import transaction
from django.utils import timezone

User = get_user_model()


@skipUnless(connection.vendor == 'postgresql', 'row-locking race test requires PostgreSQL')
class SponsorFundConcurrentScanTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        cache.clear()
        school = School.objects.create(name='Sponsor Concurrency School')
        self.operator = User.objects.create_user(username='sponsor-concurrent-operator', role='operator', school=school)
        student = User.objects.create_user(username='sponsor-concurrent-student', role='student', school=school)
        self.card = RFIDCard.objects.create(
            card_number='SPONSOR-CONCURRENT-CARD', control_number='SPONSOR-CONCURRENT-CTRL',
            student_or_staff=student, balance=Decimal('2000.00'),
        )
        self.item = CanteenItem.objects.create(name='Concurrent Meal', price=Decimal('100.00'))
        self.fund = SponsorFund.objects.create(name='Concurrent Fund', sponsor_name='Test', start_date=date.today())
        contribution = FundContribution.objects.create(
            fund=self.fund, amount=Decimal('500.00'), method='cash', reference='INITIAL',
            received_at=timezone.now(),
        )
        with transaction.atomic():
            post_fund_contribution(contribution)
        SponsorshipAllocation.objects.create(
            fund=self.fund, student=student, meal_types=['lunch'], valid_from=date.today(),
        )
        FeatureFlag.objects.update_or_create(key='SPONSORSHIP', defaults={'enabled': True})
        FeatureFlag.objects.update_or_create(key='STOCK', defaults={'enabled': True})
        self.sessions = [ScanSession.objects.create(operator=self.operator, type='lunch') for _ in range(20)]

    def _scan(self, session_id):
        close_old_connections()
        user = User.objects.get(pk=self.operator.pk)
        client = APIClient(); client.force_authenticate(user)
        response = client.post('/api/v1/sessions/scan-card', {
            'session_id': str(session_id), 'card_number': self.card.card_number,
            'item_id': str(self.item.pk),
        }, format='json')
        close_old_connections()
        return response.status_code, response.data

    def test_twenty_parallel_scans_cannot_overspend_fund(self):
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(self._scan, [row.pk for row in self.sessions]))
        self.assertTrue(all(code == 201 for code, _ in results), results)
        lines = self.fund.journal_lines.filter(account__code='2200')
        credits = sum(lines.filter(direction='credit').values_list('amount', flat=True), Decimal('0.00'))
        debits = sum(lines.filter(direction='debit').values_list('amount', flat=True), Decimal('0.00'))
        self.assertGreaterEqual(credits - debits, Decimal('0.00'))
        fund_paid = sum(TransactionPayment.objects.filter(fund=self.fund).values_list('amount', flat=True), Decimal('0.00'))
        self.assertEqual(fund_paid, Decimal('500.00'))
