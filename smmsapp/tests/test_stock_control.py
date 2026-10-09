from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from smmsapp.models import (
    CanteenItem, FeatureFlag, Notification, RFIDCard, ScanSession, School,
    StockLevel, StockMovement, Transaction,
)
from smmsapp.views.stock import notify_low_stock

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class StockControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Stock Control School')
        cls.admin = User.objects.create_user(username='stock-admin', role='admin', school=cls.school)
        cls.operator = User.objects.create_user(username='stock-operator', role='operator', school=cls.school)
        cls.student = User.objects.create_user(username='stock-student', role='student', school=cls.school)
        cls.card = RFIDCard.objects.create(
            card_number='STOCK-CARD', control_number='STOCK-CONTROL',
            student_or_staff=cls.student, balance=Decimal('5000.00'), is_active=True,
        )
        cls.item = CanteenItem.objects.create(name='Stock Meal', price=Decimal('500.00'))

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(key='STOCK', defaults={'enabled': True})
        FeatureFlag.objects.update_or_create(key='PAYMENTS', defaults={'enabled': True})
        self.session = ScanSession.objects.create(operator=self.operator, type='lunch')
        self.admin_api = APIClient()
        self.admin_api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    def scan(self, item=None):
        return self.operator_api.post('/api/v1/sessions/scan-card', {
            'session_id': str(self.session.id), 'card_number': self.card.card_number,
            'item_id': str((item or self.item).id),
        }, format='json')

    def test_adjustment_scan_and_reversal_keep_stock_movements_consistent(self):
        adjusted = self.admin_api.post('/api/v1/stock/adjust', {
            'item_id': str(self.item.id), 'delta': 2, 'low_threshold': 1,
            'reason': 'Opening stock',
        }, format='json')
        self.assertEqual(adjusted.status_code, 200, adjusted.data)
        self.assertEqual(adjusted.data['quantity'], 2)

        scanned = self.scan()
        self.assertEqual(scanned.status_code, 201, scanned.data)
        self.assertEqual(StockLevel.objects.get(item=self.item).quantity, 1)
        self.assertEqual(StockMovement.objects.filter(item=self.item).count(), 2)

        reversed_response = self.admin_api.post('/api/v1/wallet/transaction/reverse', {
            'transaction_id': str(Transaction.objects.get().id), 'reason': 'Mistaken scan',
        }, format='json')
        self.assertEqual(reversed_response.status_code, 200, reversed_response.data)
        self.assertEqual(StockLevel.objects.get(item=self.item).quantity, 2)
        self.assertEqual(StockMovement.objects.filter(item=self.item).count(), 3)

    @override_settings(STOCK_ENFORCED=True)
    def test_enforced_empty_stock_rejects_scan_without_creating_transaction(self):
        StockLevel.objects.create(item=self.item, quantity=0, low_threshold=1)
        response = self.scan()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'OUT_OF_STOCK')
        self.assertEqual(Transaction.objects.count(), 0)

    def test_stock_management_is_flag_gated(self):
        flag = FeatureFlag.objects.get(key='STOCK')
        flag.enabled = False
        flag.save(update_fields=['enabled'])
        response = self.admin_api.get('/api/v1/stock/')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'FEATURE_DISABLED')

    def test_low_stock_notifications_are_deduplicated_per_admin_and_day(self):
        StockLevel.objects.create(item=self.item, quantity=1, low_threshold=1)
        self.assertEqual(notify_low_stock(), 1)
        self.assertEqual(notify_low_stock(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.admin, dedupe_key__startswith='low_stock:').count(), 1)
