from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from smmsapp.models import (
    CanteenItem, FeatureFlag, ParentStudent, RFIDCard, ScanSession,
    ScannedData, School, Transaction,
)

User = get_user_model()


class AnalyticsEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Analytics School')
        cls.admin = User.objects.create_user(username='analytics-admin', role='admin', school=cls.school)
        cls.parent = User.objects.create_user(
            username='analytics-parent', role='parent', school=cls.school,
            balance_threshold=Decimal('1000.00'),
        )
        cls.student = User.objects.create_user(
            username='analytics-student', role='student', school=cls.school,
            class_room='Standard 3',
        )
        cls.operator = User.objects.create_user(username='analytics-operator', role='operator', school=cls.school)
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.card = RFIDCard.objects.create(
            card_number='ANALYTICS-CARD', control_number='ANALYTICS-CONTROL',
            student_or_staff=cls.student, balance=Decimal('500.00'), insufficient_meal_count=8,
        )
        cls.item = CanteenItem.objects.create(name='Analytics Meal', price=Decimal('100.00'))
        cls.session = ScanSession.objects.create(operator=cls.operator, type='lunch')

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(key='ANALYTICS', defaults={'enabled': True})
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal('100.00'), charged_amount=Decimal('100.00'),
            transaction_status='successful', session=self.session,
        )
        Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal('150.00'), charged_amount=Decimal('50.00'),
            transaction_status='penalty', session=self.session,
        )
        ScannedData.objects.create(
            session=self.session, student_or_staff=self.student, rfid_card=self.card,
            item=self.item, scan_source='nfc',
        )

    def test_sales_groupings_and_daily_totals_use_charged_amount(self):
        day = timezone.localdate().isoformat()
        response = self.api.get('/api/v1/analytics/sales', {'from': day, 'to': day})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['totals']['revenue'], Decimal('100.00'))
        self.assertEqual(response.data['totals']['penalty_amount'], Decimal('50.00'))
        self.assertEqual(response.data['totals']['count'], 2)
        self.assertEqual(response.data['series'][0]['label'], day)
        self.assertEqual(response['Cache-Control'], 'private, max-age=300')

        by_item = self.api.get('/api/v1/analytics/sales', {'from': day, 'to': day, 'group_by': 'item'})
        self.assertEqual(by_item.data['series'][0]['label'], self.item.name)

    def test_operator_class_and_penalty_reports(self):
        day = timezone.localdate().isoformat()
        operators = self.api.get('/api/v1/analytics/operators', {'from': day, 'to': day})
        row = operators.data['operators'][0]
        self.assertEqual(row['sessions'], 1)
        self.assertEqual(row['revenue'], Decimal('100.00'))
        self.assertEqual(row['nfc_share'], 1.0)

        classes = self.api.get('/api/v1/analytics/classes', {'from': day, 'to': day})
        self.assertEqual(classes.data[0]['class_room'], 'Standard 3')
        self.assertEqual(classes.data[0]['spend'], Decimal('150.00'))

        penalties = self.api.get('/api/v1/analytics/penalties', {'from': day, 'to': day})
        self.assertEqual(penalties.data['count'], 1)
        self.assertEqual(penalties.data['amount'], Decimal('50.00'))
        self.assertEqual(len(penalties.data['students_near_limit']), 1)

    def test_wallet_health_and_date_validation(self):
        wallet = self.api.get('/api/v1/analytics/wallet-health')
        self.assertEqual(wallet.status_code, 200, wallet.data)
        self.assertEqual(wallet.data['float_total'], Decimal('500.00'))
        self.assertEqual(wallet.data['below_threshold'], 1)
        self.assertEqual(wallet.data['near_strike_limit'], 1)

        invalid = self.api.get('/api/v1/analytics/sales', {'from': '2026-02-01', 'to': '2026-01-01'})
        self.assertEqual(invalid.status_code, 400)

    def test_analytics_export_uses_existing_csv_flow_and_is_admin_only(self):
        day = timezone.localdate().isoformat()
        response = self.api.post('/api/v1/exports/analytics_sales', {
            'export_format': 'csv', 'from_date': day, 'to_date': day,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Revenue', response.content.decode('utf-8-sig'))

        self.api.force_authenticate(self.parent)
        denied = self.api.post('/api/v1/exports/analytics_sales', {'export_format': 'csv'}, format='json')
        self.assertEqual(denied.status_code, 403)

    def test_sales_cache_hit_and_daily_snapshot_invalidation(self):
        from smmsapp.services.analytics import build_daily_stats_for_day

        day = timezone.localdate().isoformat()
        url = '/api/v1/analytics/sales'
        params = {'from': day, 'to': day}
        initial = self.api.get(url, params)
        Transaction.objects.create(
            student_or_staff=self.student, rfid_card=self.card, item=self.item,
            amount=Decimal('100.00'), charged_amount=Decimal('100.00'),
            transaction_status='successful', session=self.session,
        )
        cached = self.api.get(url, params)
        self.assertEqual(cached.data['totals']['revenue'], initial.data['totals']['revenue'])
        build_daily_stats_for_day(timezone.localdate())
        refreshed = self.api.get(url, params)
        self.assertEqual(refreshed.data['totals']['revenue'], Decimal('200.00'))
