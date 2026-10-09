from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from smmsapp.models import (
    AuditLog, BankDeposit, CanteenItem, DailyStats, FeatureFlag, InsightFlag,
    RFIDCard, Reconciliation, Reversal, ScanSession, ScannedData, School, Transaction,
)
from smmsapp.services.insights import build_operational_insight_flags

User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    INSIGHT_REVERSAL_LIMIT=1,
    INSIGHT_VARIANCE_LIMIT=Decimal('50.00'),
)
class InsightsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Insights School')
        cls.admin = User.objects.create_user(username='insights-admin', role='admin')
        cls.operator = User.objects.create_user(username='insights-operator', role='operator', school=cls.school)
        cls.student = User.objects.create_user(username='insights-student', role='student', school=cls.school)
        cls.card = RFIDCard.objects.create(card_number='INSIGHTS-CARD', control_number='INSIGHTS-CTRL', student_or_staff=cls.student)
        cls.item = CanteenItem.objects.create(name='Insights Meal', price=Decimal('50.00'))
        cls.session = ScanSession.objects.create(operator=cls.operator, type='lunch')

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(key='INSIGHTS', defaults={'enabled': True})
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_operational_flags_are_deduplicated(self):
        now = timezone.now()
        first = Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal('50'), charged_amount=Decimal('50'), transaction_status='successful', session=self.session,
        )
        second = Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal('50'), charged_amount=Decimal('50'), transaction_status='successful', session=self.session,
        )
        Reversal.objects.create(transaction=first, reversed_by=self.operator, reason='first')
        Reversal.objects.create(transaction=second, reversed_by=self.operator, reason='second')
        Reconciliation.objects.create(
            session=self.session, scanned_value=Decimal('50'), expected_cash=Decimal('150'),
            variance=Decimal('100'), status='variance',
        )
        scan_a = ScannedData.objects.create(session=self.session, student_or_staff=self.student, rfid_card=self.card, item=self.item)
        scan_b = ScannedData.objects.create(session=self.session, student_or_staff=self.student, rfid_card=self.card, item=self.item)
        ScannedData.objects.filter(pk=scan_a.pk).update(scanned_at=now)
        ScannedData.objects.filter(pk=scan_b.pk).update(scanned_at=now + timedelta(seconds=40))
        deposit = BankDeposit.objects.create(control_number=self.card, amount=Decimal('50'), status='pending')
        BankDeposit.objects.filter(pk=deposit.pk).update(created_at=now - timedelta(hours=25))

        self.assertEqual(build_operational_insight_flags(), 4)
        self.assertEqual(build_operational_insight_flags(), 0)
        self.assertSetEqual(
            set(InsightFlag.objects.values_list('kind', flat=True)),
            {'reversal_spike', 'session_variance', 'duplicate_scan', 'deposit_stuck'},
        )

    def test_forecast_and_anomaly_resolution_are_audited(self):
        target = timezone.localdate()
        for weeks, meals in ((2, 10), (3, 20), (4, 15)):
            DailyStats.objects.create(date=target - timedelta(days=7 * weeks), meal_type='lunch', meals=meals)
        forecast = self.api.get('/api/v1/insights/forecast', {'date': target.isoformat()})
        lunch = next(row for row in forecast.data if row['meal_type'] == 'lunch')
        self.assertEqual(lunch['expected_meals'], 15)
        self.assertEqual(lunch['weeks_used'], 3)

        flag = InsightFlag.objects.create(
            kind='session_variance', reference_type='session', reference_id=str(self.session.id),
            detail={'reason': 'pending'},
        )
        resolved = self.api.post(f'/api/v1/insights/anomalies/{flag.id}/resolve', {'note': 'Checked statement'}, format='json')
        self.assertEqual(resolved.status_code, 200, resolved.data)
        flag.refresh_from_db()
        self.assertEqual(flag.status, 'resolved')
        self.assertEqual(flag.resolved_by, self.admin)
        self.assertTrue(AuditLog.objects.filter(action='update').exists())

    def test_insights_feature_gate(self):
        FeatureFlag.objects.filter(key='INSIGHTS').update(enabled=False)
        response = self.api.get('/api/v1/insights/anomalies')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'FEATURE_DISABLED')
