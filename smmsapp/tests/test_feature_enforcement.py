from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.test import APIClient

from smmsapp.models import CanteenItem, FeatureFlag, RFIDCard, School
from smmsapp.permissions.features import FeatureEnabled

User = get_user_model()
FLAGS = {
    'ANALYTICS': False, 'INSIGHTS': False, 'LEDGER_UI': False,
    'PAYMENTS': False, 'MENU': False, 'PREORDERS': False,
    'PREORDER': False,
    'SPONSORSHIP': False, 'INTEGRATIONS': False, 'STOCK': False,
    'PARENT_LIMITS': False, 'NFC_SCAN': False,
}


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], FEATURES_DEFAULT=FLAGS)
class FeatureEnforcementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Feature API School', location='Dar es Salaam')
        cls.admin = User.objects.create_user(username='feature-admin', password='secret', role='admin', school=cls.school)
        cls.parent = User.objects.create_user(username='feature-parent', password='secret', role='parent', school=cls.school)
        cls.operator = User.objects.create_user(username='feature-operator', password='secret', role='operator', school=cls.school)
        cls.student = User.objects.create_user(username='feature-student', password='secret', role='student', school=cls.school)
        cls.card = RFIDCard.objects.create(
            card_number='NFC-UID-1', control_number='FEATURE-CTRL', student_or_staff=cls.student,
            balance=Decimal('5000.00'), is_active=True,
        )
        CanteenItem.objects.create(name='Feature Meal', price=Decimal('500.00'))

    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.flags = {
            key: FeatureFlag.objects.update_or_create(key=key, defaults={'enabled': False})[0]
            for key in FLAGS
        }

    def _enable(self, key):
        flag = self.flags[key]
        flag.enabled = True
        flag.save()

    def test_analytics_flag_closes_and_opens_analytics_endpoint(self):
        self.api.force_authenticate(self.admin)
        url = '/api/v1/dashboard/sales-summary'
        response = self.api.post(url, {'filter': 'day'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'FEATURE_DISABLED')
        self._enable('ANALYTICS')
        self.assertEqual(self.api.post(url, {'filter': 'day'}, format='json').status_code, 200)

    def test_ledger_payments_and_menu_flags(self):
        self.api.force_authenticate(self.admin)
        cases = [
            ('LEDGER_UI', 'get', '/api/v1/wallet/ledger/card?card_number=NFC-UID-1', None),
            ('PAYMENTS', 'get', '/api/v1/wallet/deposit/list', None),
            ('MENU', 'post', '/api/v1/resources/item-list/', {},),
        ]
        for key, method, url, data in cases:
            with self.subTest(feature=key):
                disabled = getattr(self.api, method)(url, data) if data is not None else getattr(self.api, method)(url)
                self.assertEqual(disabled.status_code, 403)
                self.assertEqual(disabled.json()['code'], 'FEATURE_DISABLED')
                self._enable(key)
                enabled = getattr(self.api, method)(url, data) if data is not None else getattr(self.api, method)(url)
                self.assertNotEqual(enabled.status_code, 403)
                self.assertNotEqual(enabled.json().get('code') if isinstance(enabled.json(), dict) else None, 'FEATURE_DISABLED')

    def test_parent_limits_flag_and_conditional_nfc_gate(self):
        self.api.force_authenticate(self.parent)
        response = self.api.get('/api/v1/dashboard/balance-threshold')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'FEATURE_DISABLED')
        self._enable('PARENT_LIMITS')
        self.assertEqual(self.api.get('/api/v1/dashboard/balance-threshold').status_code, 200)

        self.api.force_authenticate(self.operator)
        nfc_payload = {'session_id': '00000000-0000-0000-0000-000000000000', 'card_uid': 'NFC-UID-1'}
        response = self.api.post('/api/v1/sessions/scan-card', nfc_payload, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'FEATURE_DISABLED')
        self._enable('NFC_SCAN')
        response = self.api.post('/api/v1/sessions/scan-card', nfc_payload, format='json')
        self.assertNotEqual(response.status_code, 403)
        self.assertNotEqual(response.json().get('code'), 'FEATURE_DISABLED')

    def test_rfid_card_number_scan_is_not_gated_by_nfc_flag(self):
        self.api.force_authenticate(self.operator)
        response = self.api.post('/api/v1/sessions/scan-card', {
            'session_id': '00000000-0000-0000-0000-000000000000',
            'card_number': 'NFC-UID-1',
        }, format='json')
        self.assertNotEqual(response.status_code, 403)
        self.assertNotEqual(response.json().get('code'), 'FEATURE_DISABLED')

    def test_flags_without_implemented_routes_are_known_but_default_off(self):
        for key in ('INSIGHTS', 'PREORDERS', 'SPONSORSHIP', 'INTEGRATIONS', 'STOCK'):
            with self.subTest(feature=key):
                self.assertFalse(self.flags[key].enabled)

    def test_permission_factory_enforces_every_catalog_flag(self):
        factory = APIRequestFactory()
        for key in FLAGS:
            with self.subTest(feature=key):
                raw = factory.post('/feature-probe', {'card_uid': 'uid'}) if key == 'NFC_SCAN' else factory.get('/feature-probe')
                permission = FeatureEnabled(key)()
                request = Request(raw)
                self.assertFalse(permission.has_permission(request, view=None))
                self._enable(key)
                self.assertTrue(permission.has_permission(request, view=None))
