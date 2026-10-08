import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from smmsapp.models import CanteenItem, FeatureFlag, RFIDCard, ScanSession, School, ScannedData, Transaction
from smmsapp.services.cards import normalize_uid
from smmsapp.services.insights import build_impossible_scan_flags

User = get_user_model()


class NormalizeUIDTests(TestCase):
    def test_normalizes_separators_case_and_supported_lengths(self):
        self.assertEqual(normalize_uid('04:a1-b2 c3'), '04A1B2C3')
        self.assertEqual(normalize_uid('04:a1:b2:c3:d4:e5:f6'), '04A1B2C3D4E5F6')
        self.assertEqual(normalize_uid('00112233445566778899'), '00112233445566778899')

    def test_rejects_invalid_hex_or_unsupported_length(self):
        for value in ('xyz', 'AABBCC', '00112233445566778899AA', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_uid(value)


@override_settings(SCAN_THROTTLE_RATE=120)
class ScanByUIDTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='UID Scan School', location='Dar es Salaam')
        cls.operator = User.objects.create_user(username='uid-operator', password='secret', role='operator', school=cls.school)
        cls.student = User.objects.create_user(username='uid-student', password='secret', role='student', school=cls.school)
        cls.card = RFIDCard.objects.create(card_number='CARD-UID-1', uid_hex='04A1B2C3', control_number='UID-CONTROL-1', student_or_staff=cls.student, balance=Decimal('5000'))
        cls.item = CanteenItem.objects.create(name='UID Meal', price=Decimal('500'))

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(key='NFC_SCAN', defaults={'enabled': True})
        self.session = ScanSession.objects.create(operator=self.operator, type='lunch')
        self.api = APIClient()
        self.api.force_authenticate(self.operator)

    def scan(self, **extra):
        payload = {'session_id': str(self.session.id), 'card_uid': '04:a1-b2-c3', 'item_id': str(self.item.id)}
        payload.update(extra)
        return self.api.post('/api/v1/sessions/scan-card', payload, format='json')

    def test_uid_scan_resolves_card_and_records_nfc_source(self):
        response = self.scan()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['card_number'], self.card.card_number)
        self.assertEqual(response.data['scan_source'], 'nfc')
        self.assertEqual(Transaction.objects.get().scan_source, 'nfc')

    def test_unknown_uid_returns_not_found(self):
        response = self.scan(card_uid='04:FF:FF:FF')
        self.assertEqual(response.status_code, 404)

    def test_exactly_one_identifier_is_required(self):
        self.assertEqual(self.scan(card_number='CARD-UID-1').status_code, 400)
        payload = {'session_id': str(self.session.id), 'item_id': str(self.item.id)}
        self.assertEqual(self.api.post('/api/v1/sessions/scan-card', payload, format='json').data['code'], 'CARD_IDENTIFIER_REQUIRED')

    def test_client_scan_id_is_idempotent(self):
        scan_id = str(uuid.uuid4())
        first = self.scan(client_scan_id=scan_id)
        second = self.scan(client_scan_id=scan_id)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(ScannedData.objects.count(), 1)

    @override_settings(SCAN_THROTTLE_RATE=1)
    def test_operator_is_throttled_after_configured_rate(self):
        self.assertEqual(self.scan().status_code, 201)
        response = self.scan(client_scan_id=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 429)


class ImpossibleScanTests(TestCase):
    def test_flags_same_card_in_different_operator_sessions_within_two_minutes(self):
        school = School.objects.create(name='Insight Scan School')
        student = User.objects.create_user(username='insight-student', role='student', school=school)
        op_a = User.objects.create_user(username='insight-op-a', role='operator', school=school)
        op_b = User.objects.create_user(username='insight-op-b', role='operator', school=school)
        card = RFIDCard.objects.create(card_number='INSIGHT-CARD', uid_hex='11223344', control_number='INSIGHT-CTRL', student_or_staff=student)
        item = CanteenItem.objects.create(name='Insight Meal', price=Decimal('10'))
        session_a = ScanSession.objects.create(operator=op_a, type='lunch')
        session_b = ScanSession.objects.create(operator=op_b, type='lunch')
        first = ScannedData.objects.create(session=session_a, student_or_staff=student, rfid_card=card, item=item)
        second = ScannedData.objects.create(session=session_b, student_or_staff=student, rfid_card=card, item=item)
        first_at = timezone.now()
        ScannedData.objects.filter(pk=first.pk).update(scanned_at=first_at)
        ScannedData.objects.filter(pk=second.pk).update(scanned_at=first_at + timedelta(minutes=1))

        self.assertEqual(build_impossible_scan_flags(), 1)
        self.assertEqual(build_impossible_scan_flags(), 0)


class OperatorNFCShareTests(TestCase):
    def test_analytics_reports_nfc_share_per_operator(self):
        cache.clear()
        school = School.objects.create(name='NFC Share School')
        admin = User.objects.create_user(username='nfc-share-admin', password='secret', role='admin', school=school)
        operator = User.objects.create_user(username='nfc-share-op', role='operator', school=school)
        student = User.objects.create_user(username='nfc-share-student', role='student', school=school)
        card = RFIDCard.objects.create(card_number='SHARE-CARD', control_number='SHARE-CTRL', student_or_staff=student)
        item = CanteenItem.objects.create(name='Share Meal', price=Decimal('10'))
        session = ScanSession.objects.create(operator=operator, type='breakfast')
        ScannedData.objects.create(session=session, student_or_staff=student, rfid_card=card, item=item, scan_source='nfc')
        ScannedData.objects.create(session=session, student_or_staff=student, rfid_card=card, item=item, scan_source='usb')
        FeatureFlag.objects.update_or_create(key='ANALYTICS', defaults={'enabled': True})
        api = APIClient()
        api.force_authenticate(admin)

        response = api.get('/api/v1/analytics/operators')

        self.assertEqual(response.status_code, 200, response.data)
        row = next(row for row in response.data['operators'] if row['operator_id'] == str(operator.id))
        self.assertEqual(row['nfc_scans'], 1)
        self.assertEqual(row['total_scans'], 2)
        self.assertEqual(row['nfc_share'], 0.5)


class CardUIDRegistrationTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='UID Registration School')
        self.admin = User.objects.create_user(username='uid-admin', password='secret', role='admin', school=self.school)
        self.student = User.objects.create_user(username='uid-registration-student', role='student', school=self.school)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_create_card_with_uid_only_generates_a_card_number(self):
        response = self.api.post('/api/v1/resources/create-card', {
            'student_or_staff': str(self.student.id), 'card_uid': 'aa:bb:cc:dd',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        card = RFIDCard.objects.get(student_or_staff=self.student)
        self.assertEqual(card.uid_hex, 'AABBCCDD')
        self.assertTrue(card.card_number.startswith('CARD-'))

    def test_uid_cannot_equal_another_card_number(self):
        other = User.objects.create_user(username='uid-other-student', role='student', school=self.school)
        RFIDCard.objects.create(card_number='AABBCCDD', control_number='UID-OTHER-CTRL', student_or_staff=other)
        response = self.api.post('/api/v1/resources/create-card', {
            'student_or_staff': str(self.student.id), 'card_uid': 'AA:BB:CC:DD',
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'CARD_UID_CONFLICT')

    def test_replace_card_accepts_uid_and_carries_balance(self):
        old = RFIDCard.objects.create(
            card_number='OLD-UID-CARD', control_number='OLD-UID-CTRL',
            student_or_staff=self.student, balance=Decimal('1234.00'), is_active=True,
        )
        response = self.api.post('/api/v1/resources/replace-card', {
            'old_card_id': str(old.id), 'card_uid': '01:02:03:04',
            'carry_balance': True, 'reason': 'NFC replacement',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        replacement = RFIDCard.objects.get(id=response.data['new_card_id'])
        self.assertEqual(replacement.uid_hex, '01020304')
        self.assertEqual(replacement.balance, Decimal('1234.00'))
        old.refresh_from_db()
        self.assertFalse(old.is_active)
