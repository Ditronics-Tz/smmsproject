from datetime import timedelta
from datetime import date
from decimal import Decimal
import random
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from smmsapp.models import (CanteenItem, DailyMenu, DailyMenuItem, FeatureFlag,
    JournalEntry, ParentStudent, PreOrder, PreOrderItem, RFIDCard, School,
    ScanSession, Transaction)
from smmsapp.services.ledger import check_ledger_integrity, post_opening
from smmsapp.services.preorders import (
    cutoff_for, fulfil_preorder_item, place_preorder, preorder_notification_content,
    release_preorder,
)

User = get_user_model()


class PreOrderNotificationTemplateTests(SimpleTestCase):
    def setUp(self):
        self.order = type('OrderStub', (), {'date': date(2026, 10, 10)})()

    @override_settings(APP_LOCALE='en-TZ')
    def test_english_no_show_includes_return_amount(self):
        title, message = preorder_notification_content(self.order, 'no_show', Decimal('125.50'))
        self.assertEqual(title, 'Pre-order not served')
        self.assertIn('Amount returned: TZS 125.50', message)

    @override_settings(APP_LOCALE='sw-TZ')
    def test_swahili_order_and_fulfilment_templates_are_available(self):
        title, message = preorder_notification_content(self.order, 'placed')
        self.assertEqual(title, 'Oda imepokelewa')
        self.assertIn('imepokelewa', message)
        self.assertIn('imetimizwa', preorder_notification_content(self.order, 'fulfilled')[1])



@override_settings(PREORDER_CUTOFF_TIME='23:59', PREORDER_MAX_QTY_PER_ITEM=1)
class PreOrderServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        school = School.objects.create(name='Preorder test school')
        cls.parent = User.objects.create_user(username='preorder-parent', password='test', role='parent', school=school)
        cls.operator = User.objects.create_user(username='preorder-operator', password='test', role='operator', school=school)
        cls.student = User.objects.create_user(username='preorder-child', password='test', role='student', school=school)
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.card = RFIDCard.objects.create(card_number='PREORDER-CARD', control_number='PREORDER-CONTROL', student_or_staff=cls.student, balance=Decimal('1000.00'))
        cls.item = CanteenItem.objects.create(name='Rice', price=Decimal('250.00'))
        cls.day = timezone.localdate() + timedelta(days=1)
        cls.menu = DailyMenu.objects.create(date=cls.day, meal_type='lunch')
        DailyMenuItem.objects.create(menu=cls.menu, item=cls.item, price_override=Decimal('200.00'))

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(key='PREORDER', defaults={'enabled': True})

    def _place(self, key='preorder-idempotency'):
        return place_preorder(
            student=self.student, card=self.card, order_date=self.day, meal_type='lunch',
            rows=[(self.item, 1, Decimal('200.00'))], idempotency_key=key, actor=self.parent,
        )

    def test_cutoff_is_previous_day_in_tanzania(self):
        cutoff = cutoff_for(self.day)
        self.assertEqual(cutoff.hour, 23)
        self.assertEqual(cutoff.minute, 59)
        self.assertEqual(cutoff.date(), self.day - timedelta(days=1))

    def test_place_holds_money_and_is_idempotent(self):
        order = self._place()
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('800.00'))
        self.assertEqual(self.card.held_balance, Decimal('200.00'))
        self.assertEqual(self._place().pk, order.pk)
        self.assertEqual(JournalEntry.objects.filter(idempotency_key=f'preorder-hold:{order.id}').count(), 1)

    def test_fulfil_transfers_hold_to_revenue_without_wallet_deduction(self):
        order = self._place()
        fulfilled = fulfil_preorder_item(order, self.item, actor=self.parent)
        self.assertEqual(fulfilled.fulfilled_quantity, 1)
        self.card.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('800.00'))
        self.assertEqual(self.card.held_balance, Decimal('0.00'))
        self.assertEqual(order.status, 'fulfilled')

    def test_cancel_releases_hold(self):
        order = self._place()
        release_preorder(order, actor=self.parent)
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('1000.00'))
        self.assertEqual(self.card.held_balance, Decimal('0.00'))
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')

    def test_negative_wallet_cannot_order(self):
        self.card.balance = Decimal('-1.00')
        self.card.save(update_fields=['balance'])
        with self.assertRaisesMessage(ValueError, 'PREORDER_INSUFFICIENT_BALANCE'):
            self._place()

    def test_wallet_exactly_equal_to_hold_can_order(self):
        self.card.balance = Decimal('200.00')
        self.card.save(update_fields=['balance'])
        self._place()
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('0.00'))

    def test_quantity_above_configured_limit_is_rejected(self):
        with self.assertRaisesMessage(ValueError, 'PREORDER_QUANTITY_LIMIT'):
            place_preorder(
                student=self.student, card=self.card, order_date=self.day, meal_type='lunch',
                rows=[(self.item, 2, Decimal('200.00'))],
                idempotency_key='too-many-rice', actor=self.parent,
            )

    def test_second_active_order_for_same_meal_is_rejected(self):
        self._place(key='first-active-order')
        with self.assertRaisesMessage(ValueError, 'PREORDER_CONFLICT'):
            self._place(key='second-active-order')

    def test_cancel_after_cutoff_is_rejected_without_releasing_hold(self):
        cutoff = cutoff_for(self.day)
        with patch('smmsapp.services.preorders.timezone.now', return_value=cutoff - timedelta(seconds=1)):
            order = self._place(key='cancel-boundary-order')
        api = APIClient()
        api.force_authenticate(self.parent)
        with patch('smmsapp.views.preorders.timezone.now', return_value=cutoff + timedelta(seconds=1)):
            response = api.post('/api/v1/preorders/cancel', {'preorder_id': str(order.id)}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'PREORDER_NOT_CANCELLABLE')
        self.card.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(order.status, 'placed')
        self.assertEqual(self.card.held_balance, Decimal('200.00'))

    def test_cutoff_boundary_one_second_before_and_after(self):
        cutoff = cutoff_for(self.day)
        with patch('smmsapp.services.preorders.timezone.now', return_value=cutoff - timedelta(seconds=1)):
            self._place(key='before-cutoff')
        self.card.balance = Decimal('1000.00')
        self.card.held_balance = Decimal('0.00')
        self.card.save(update_fields=['balance', 'held_balance'])
        with patch('smmsapp.services.preorders.timezone.now', return_value=cutoff + timedelta(seconds=1)):
            with self.assertRaisesMessage(ValueError, 'PREORDER_CUTOFF_PASSED'):
                self._place(key='after-cutoff')

    @override_settings(PREORDER_NOSHOW_FEE=Decimal('25.00'))
    def test_no_show_returns_remaining_hold_less_fee(self):
        order = self._place()
        release_preorder(order, status_value='no_show', fee=Decimal('25.00'))
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('975.00'))
        self.assertEqual(self.card.held_balance, Decimal('0.00'))
        order.refresh_from_db()
        self.assertEqual(order.status, 'no_show')

    def test_nightly_task_expires_and_releases_an_unserved_old_order(self):
        with transaction.atomic():
            post_opening(self.card)
        order = PreOrder.objects.create(
            student=self.student, card=self.card, date=timezone.localdate() - timedelta(days=1),
            meal_type='lunch', total_amount=Decimal('200.00'), cutoff_at=timezone.now() - timedelta(days=1),
            idempotency_key='expired-order', created_by=self.parent,
        )
        PreOrderItem.objects.create(preorder=order, item=self.item, quantity=1, unit_price=Decimal('200.00'))
        self.card.balance = Decimal('800.00')
        self.card.held_balance = Decimal('200.00')
        self.card.save(update_fields=['balance', 'held_balance'])
        from smmsapp.services.ledger import post_preorder_hold
        with transaction.atomic():
            post_preorder_hold(order)
        from smmsapp.tasks import expire_preorders
        self.assertEqual(expire_preorders.run(), 1)
        order.refresh_from_db()
        self.card.refresh_from_db()
        self.assertEqual(order.status, 'expired')
        self.assertEqual(self.card.balance, Decimal('1000.00'))
        self.assertEqual(self.card.held_balance, Decimal('0.00'))

    def test_parent_cannot_read_an_unlinked_child_preorder(self):
        other = User.objects.create_user(username='other-preorder-child', password='test', role='student')
        api = APIClient()
        api.force_authenticate(self.parent)
        response = api.get('/api/v1/preorders/menu', {'date': self.day.isoformat(), 'child_id': str(other.id)})
        self.assertEqual(response.status_code, 404)

    def test_parent_can_create_and_list_own_order(self):
        api = APIClient()
        api.force_authenticate(self.parent)
        payload = {
            'child_id': str(self.student.id), 'date': self.day.isoformat(), 'meal_type': 'lunch',
            'idempotency_key': 'api-create-order',
            'items': [{'item_id': str(self.item.id), 'quantity': 1}],
        }
        created = api.post('/api/v1/preorders/create', payload, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        repeated = api.post('/api/v1/preorders/create', payload, format='json')
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data['id'], created.data['id'])
        listed = api.get('/api/v1/preorders/list')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data['results']), 1)

    def test_preorder_flag_returns_403_when_disabled(self):
        flag = FeatureFlag.objects.get(key='PREORDER')
        flag.enabled = False
        flag.save()
        cache.clear()
        api = APIClient()
        api.force_authenticate(self.parent)
        response = api.get('/api/v1/preorders/menu', {
            'date': self.day.isoformat(), 'child_id': str(self.student.id),
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'FEATURE_DISABLED')

    def test_replacement_moves_the_order_and_held_balance_to_new_card(self):
        order = self._place()
        api = APIClient()
        admin = User.objects.create_user(username='preorder-admin', password='test', role='admin', school=self.student.school)
        api.force_authenticate(admin)
        response = api.post('/resources/replace-card', {
            'old_card_id': str(self.card.id), 'new_card_number': 'PREORDER-CARD-NEW',
            'reason': 'lost', 'carry_balance': True,
        })
        self.assertEqual(response.status_code, 200, response.data)
        order.refresh_from_db()
        self.card.refresh_from_db()
        new_card = RFIDCard.objects.get(card_number='PREORDER-CARD-NEW')
        self.assertEqual(order.card_id, new_card.id)
        self.assertEqual(new_card.held_balance, Decimal('200.00'))
        self.assertEqual(self.card.held_balance, Decimal('0.00'))
        self.assertFalse(self.card.is_active)

    def test_scan_fulfils_matching_order_and_reversal_refunds_wallet(self):
        with transaction.atomic():
            post_opening(self.card)
        cutoff = timezone.now() + timedelta(hours=1)
        order = PreOrder.objects.create(
            student=self.student, card=self.card, date=timezone.localdate(), meal_type='lunch',
            status='placed', total_amount=Decimal('200.00'), cutoff_at=cutoff,
            idempotency_key='scan-preorder', created_by=self.parent,
        )
        order_item = PreOrderItem.objects.create(preorder=order, item=self.item, quantity=1, unit_price=Decimal('200.00'))
        self.card.balance = Decimal('800.00')
        self.card.held_balance = Decimal('200.00')
        self.card.save(update_fields=['balance', 'held_balance'])
        from smmsapp.services.ledger import post_preorder_hold
        with transaction.atomic():
            post_preorder_hold(order, actor=self.parent)
        session = ScanSession.objects.create(operator=self.operator, type='lunch')
        api = APIClient()
        api.force_authenticate(self.operator)
        response = api.post('/api/v1/sessions/scan-card', {
            'session_id': str(session.id), 'card_number': self.card.card_number,
            'item_id': str(self.item.id),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['preorder_fulfilled'])
        self.assertEqual(response.data['payment_breakdown'], [{'source': 'preorder', 'amount': '200.00'}])
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('800.00'))
        self.assertEqual(self.card.held_balance, Decimal('0.00'))
        txn = Transaction.objects.get(preorder_item=order_item)
        response = api.post('/api/v1/wallet/transaction/reverse', {
            'transaction_id': str(txn.id), 'reason': 'Incorrect fulfilment',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.card.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('1000.00'))
        self.assertEqual(order.status, 'cancelled')

    def test_integrity_after_random_sequence_of_200_orders(self):
        rng = random.Random(149155)
        with transaction.atomic():
            post_opening(self.card)
        for index in range(200):
            day = self.day + timedelta(days=index)
            order = place_preorder(
                student=self.student, card=self.card, order_date=day, meal_type='lunch',
                rows=[(self.item, 1, Decimal('1.00'))],
                idempotency_key=f'random-order-{index}', actor=self.parent,
            )
            if rng.choice((True, False)):
                fulfil_preorder_item(order, self.item, actor=self.parent)
            else:
                release_preorder(order, actor=self.parent)
        self.assertEqual(check_ledger_integrity(persist=False)['status'], 'ok')
