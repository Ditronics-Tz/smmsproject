from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from smmsapp.models import (CanteenItem, DailyMenu, DailyMenuItem, FeatureFlag,
    LedgerEntry, PreOrder, PreOrderItem, RFIDCard, ScanSession, School)

User = get_user_model()


class DailyMenuTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Daily Menu Test School')
        cls.admin = User.objects.create_user(username='menu-admin', password='secret', role='admin', school=cls.school)
        cls.operator = User.objects.create_user(username='menu-operator', password='secret', role='operator', school=cls.school)
        cls.student = User.objects.create_user(username='menu-student', password='secret', role='student', school=cls.school)
        cls.card = RFIDCard.objects.create(
            card_number='MENU-CARD-1', control_number='MENU-CONTROL-1',
            student_or_staff=cls.student, balance=Decimal('5000.00'), is_active=True,
        )
        cls.item = CanteenItem.objects.create(name='Menu Rice', price=Decimal('500.00'))

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(key='MENU', defaults={'enabled': True})
        self.admin_api = APIClient()
        self.admin_api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    def _create_menu(self, date=None, item=None, meal='lunch', override='200.00'):
        response = self.admin_api.post('/api/v1/menu/daily', {
            'date': (date or timezone.localdate()).isoformat(),
            'meal_type': meal,
            'items': [{'item_id': str((item or self.item).id), 'price_override': override}],
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return DailyMenu.objects.get(id=response.data['id'])

    def test_operator_gets_menu_price_and_admin_creates_menu(self):
        menu = self._create_menu()
        response = self.operator_api.get('/api/v1/menu/today?meal_type=lunch')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['id'], str(menu.id))
        self.assertEqual(response.data['items'][0]['price'], Decimal('200.00'))

    def test_scan_uses_menu_override_when_enforcement_enabled(self):
        self._create_menu()
        session = ScanSession.objects.create(operator=self.operator, type='lunch')
        with override_settings(MENU_ENFORCED=True):
            response = self.operator_api.post('/api/v1/sessions/scan-card', {
                'session_id': str(session.id), 'card_number': self.card.card_number,
                'item_id': str(self.item.id),
            }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('4800.00'))
        self.assertEqual(LedgerEntry.objects.get(ref_transaction__isnull=False).amount, Decimal('-200.00'))

    def test_enforced_menu_rejects_item_not_on_menu(self):
        other = CanteenItem.objects.create(name='Other meal', price=Decimal('100.00'))
        self._create_menu()
        session = ScanSession.objects.create(operator=self.operator, type='lunch')
        with override_settings(MENU_ENFORCED=True):
            response = self.operator_api.post('/api/v1/sessions/scan-card', {
                'session_id': str(session.id), 'card_number': self.card.card_number,
                'item_id': str(other.id),
            }, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'ITEM_NOT_ON_MENU')

    def test_parent_cannot_manage_menu(self):
        parent = User.objects.create_user(username='menu-parent', password='secret', role='parent', school=self.school)
        client = APIClient()
        client.force_authenticate(parent)
        response = client.get('/api/v1/menu/daily')
        self.assertEqual(response.status_code, 403)

    def test_copy_copies_meal_and_price_override(self):
        source_date = timezone.localdate() + timedelta(days=1)
        target_date = source_date + timedelta(days=1)
        self._create_menu(date=source_date)
        response = self.admin_api.post('/api/v1/menu/copy', {
            'source_date': source_date.isoformat(), 'target_date': target_date.isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        copied = DailyMenu.objects.get(date=target_date, meal_type='lunch')
        self.assertEqual(copied.items.get().price_override, Decimal('200.00'))

    def test_menu_item_cannot_be_removed_with_active_preorder(self):
        day = timezone.localdate() + timedelta(days=1)
        menu = self._create_menu(date=day)
        parent = User.objects.create_user(username='menu-preorder-parent', password='secret', role='parent', school=self.school)
        order = PreOrder.objects.create(
            student=self.student, card=self.card, date=day, meal_type='lunch',
            total_amount=Decimal('200.00'), cutoff_at=timezone.now() + timedelta(hours=1),
            idempotency_key='menu-protection-order', created_by=parent,
        )
        PreOrderItem.objects.create(preorder=order, item=self.item, quantity=1, unit_price=Decimal('200.00'))
        replacement_item = CanteenItem.objects.create(name='Replacement menu item', price=Decimal('100.00'))
        response = self.admin_api.put(f'/api/v1/menu/daily/{menu.id}', {
            'date': day.isoformat(), 'meal_type': 'lunch',
            'items': [{'item_id': str(replacement_item.id)}],
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'MENU_ITEM_HAS_PREORDERS')
        self.assertTrue(DailyMenuItem.objects.filter(menu=menu, item=self.item).exists())
