from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from smmsapp.models import (
    BlockedItem, CanteenItem, FeatureFlag, ParentStudent, RFIDCard,
    ScanSession, School, SpendingRule, Transaction,
)

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ParentControlsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Parent Controls School')
        cls.parent = User.objects.create_user(username='controls-parent', role='parent', school=cls.school)
        cls.other_parent = User.objects.create_user(username='controls-other-parent', role='parent', school=cls.school)
        cls.student = User.objects.create_user(username='controls-student', role='student', school=cls.school)
        cls.other_student = User.objects.create_user(username='controls-other-student', role='student', school=cls.school)
        cls.operator = User.objects.create_user(username='controls-operator', role='operator', school=cls.school)
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        ParentStudent.objects.create(parent=cls.other_parent, student=cls.other_student)
        cls.card = RFIDCard.objects.create(
            card_number='CONTROLS-CARD', control_number='CONTROLS-CONTROL',
            student_or_staff=cls.student, balance=Decimal('5000.00'), is_active=True,
        )
        cls.item = CanteenItem.objects.create(name='Controls Meal', price=Decimal('500.00'))
        cls.session = ScanSession.objects.create(operator=cls.operator, type='lunch')

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(key='PARENT_LIMITS', defaults={'enabled': True})
        self.parent_api = APIClient()
        self.parent_api.force_authenticate(self.parent)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    def test_parent_can_set_and_read_controls_only_for_linked_child(self):
        url = '/api/v1/resources/parent-controls'
        response = self.parent_api.put(url, {
            'child_id': str(self.student.id),
            'daily_limit': '1000.00',
            'blocked_item_ids': [str(self.item.id)],
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['daily_limit'], '1000.00')
        self.assertEqual(response.data['blocked_item_ids'], [str(self.item.id)])
        self.assertTrue(SpendingRule.objects.filter(student=self.student, daily_limit=Decimal('1000.00')).exists())
        self.assertTrue(BlockedItem.objects.filter(student=self.student, item=self.item).exists())

        read = self.parent_api.get(url, {'child_id': str(self.student.id)})
        self.assertEqual(read.status_code, 200, read.data)
        self.assertEqual(read.data['daily_limit'], '1000.00')

        forbidden = self.parent_api.get(url, {'child_id': str(self.other_student.id)})
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.data['code'], 'CHILD_NOT_LINKED')
        malformed = self.parent_api.get(url, {'child_id': 'not-a-uuid'})
        self.assertEqual(malformed.status_code, 400)

        self.operator_api.force_authenticate(self.operator)
        role_denied = self.operator_api.get(url, {'child_id': str(self.student.id)})
        self.assertEqual(role_denied.status_code, 403)

    def test_blocked_item_rejected_at_scan(self):
        BlockedItem.objects.create(student=self.student, item=self.item)
        response = self.operator_api.post('/api/v1/sessions/scan-card', {
            'session_id': str(self.session.id), 'card_number': self.card.card_number,
            'item_id': str(self.item.id),
        }, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'ITEM_BLOCKED')
        self.assertEqual(Transaction.objects.count(), 0)

    def test_daily_limit_denies_overage_but_allows_exact_boundary(self):
        SpendingRule.objects.create(student=self.student, daily_limit=Decimal('500.00'))
        exact = self.operator_api.post('/api/v1/sessions/scan-card', {
            'session_id': str(self.session.id), 'card_number': self.card.card_number,
            'item_id': str(self.item.id),
        }, format='json')
        self.assertEqual(exact.status_code, 201, exact.data)

        extra_item = CanteenItem.objects.create(name='Extra Meal', price=Decimal('1.00'))
        extra = self.operator_api.post('/api/v1/sessions/scan-card', {
            'session_id': str(self.session.id), 'card_number': self.card.card_number,
            'item_id': str(extra_item.id),
        }, format='json')
        self.assertEqual(extra.status_code, 403)
        self.assertEqual(extra.data['code'], 'DAILY_LIMIT')
        self.assertEqual(Transaction.objects.count(), 1)

    def test_feature_flag_closes_parent_control_api(self):
        flag = FeatureFlag.objects.get(key='PARENT_LIMITS')
        flag.enabled = False
        flag.save(update_fields=['enabled'])
        response = self.parent_api.get('/api/v1/resources/parent-controls', {'child_id': str(self.student.id)})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'FEATURE_DISABLED')
