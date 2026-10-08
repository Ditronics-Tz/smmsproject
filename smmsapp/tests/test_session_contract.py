from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from smmsapp.models import CanteenItem, RFIDCard, ScanSession, ScannedData, School, Transaction

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SessionContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        school = School.objects.create(name='Session Contract School', location='Dar es Salaam')
        cls.operator = User.objects.create_user(
            username='summary-operator', password='secret', role='operator', school=school,
        )
        cls.student = User.objects.create_user(
            username='summary-student', password='secret', role='student', school=school,
        )
        cls.card = RFIDCard.objects.create(
            card_number='SUMMARY-CARD', control_number='SUMMARY-CTRL',
            student_or_staff=cls.student, balance=Decimal('1000.00'), is_active=True,
        )
        cls.normal_item = CanteenItem.objects.create(name='Normal meal', price=Decimal('100.00'))
        cls.penalty_item = CanteenItem.objects.create(name='Penalty meal', price=Decimal('200.00'))
        cls.reversed_item = CanteenItem.objects.create(name='Reversed meal', price=Decimal('300.00'))

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.operator)
        self.session = ScanSession.objects.create(operator=self.operator, type='lunch', status='active')
        records = [
            (self.normal_item, Decimal('100.00'), 'successful', False),
            (self.penalty_item, Decimal('700.00'), 'penalty', False),
            (self.reversed_item, Decimal('300.00'), 'successful', True),
        ]
        for item, amount, tx_status, voided in records:
            Transaction.objects.create(
                student_or_staff=self.student, rfid_card=self.card, item=item,
                amount=amount, transaction_status=tx_status, session=self.session,
                is_voided=voided,
            )
            ScannedData.objects.create(
                session=self.session, student_or_staff=self.student,
                rfid_card=self.card, item=item,
            )

    def test_end_session_contract_excludes_penalty_and_reversed_scans(self):
        response = self.api.post('/api/v1/sessions/end-session', {
            'session_id': str(self.session.id), 'expected_cash': '110.00',
        }, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()), {
            'scanned_value', 'penalty_value', 'expected_cash', 'variance', 'status',
        })
        self.assertEqual(response.json(), {
            'scanned_value': '100.00', 'penalty_value': '500.00',
            'expected_cash': '110.00', 'variance': '10.00', 'status': 'variance',
        })

    def test_session_list_includes_summary_fields(self):
        response = self.api.post('/api/v1/sessions/session-list', {}, format='json')
        self.assertEqual(response.status_code, 200)
        row = response.json()[0]
        for key in ('scanned_value', 'penalty_value', 'expected_cash', 'variance', 'status'):
            self.assertIn(key, row)
        self.assertEqual(row['scanned_value'], '100.00')
        self.assertEqual(row['penalty_value'], '500.00')
