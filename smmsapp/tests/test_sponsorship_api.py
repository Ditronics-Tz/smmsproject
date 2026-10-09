from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from smmsapp.models import (
    AuditLog, CanteenItem, FeatureFlag, FundContribution, InsightFlag, Notification,
    RFIDCard, ScanSession, School, SponsorFund, SponsorshipAllocation, Transaction,
    TransactionPayment,
)

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SponsorshipApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.school = School.objects.create(name='Sponsor API School')
        self.admin = User.objects.create_user(username='sponsor-api-admin', role='admin', school=self.school)
        self.operator = User.objects.create_user(username='sponsor-api-operator', role='operator', school=self.school)
        self.student = User.objects.create_user(username='sponsor-api-student', role='student', school=self.school, class_room='A')
        self.card = RFIDCard.objects.create(
            card_number='SPONSOR-API-CARD', control_number='SPONSOR-API-CONTROL',
            student_or_staff=self.student, balance=Decimal('500.00'),
        )
        self.item = CanteenItem.objects.create(name='Bursary Lunch', price=Decimal('100.00'))
        self.fund = SponsorFund.objects.create(
            name='API Lunch Fund', sponsor_name='Community', start_date=date.today(), created_by=self.admin,
        )
        FeatureFlag.objects.update_or_create(key='SPONSORSHIP', defaults={'enabled': True})
        FeatureFlag.objects.update_or_create(key='STOCK', defaults={'enabled': True})
        FeatureFlag.objects.update_or_create(key='PAYMENTS', defaults={'enabled': True})
        self.admin_api = APIClient(); self.admin_api.force_authenticate(self.admin)
        self.operator_api = APIClient(); self.operator_api.force_authenticate(self.operator)
        self.parent = User.objects.create_user(username='sponsor-api-parent', role='parent')
        self.parent_api = APIClient(); self.parent_api.force_authenticate(self.parent)

    def contribute(self, amount='500.00'):
        return self.admin_api.post(f'/api/v1/sponsorship/funds/{self.fund.pk}/contribute', {
            'amount': amount, 'method': 'bank', 'reference': 'BANK-123', 'received_at': timezone.now().isoformat(),
        }, format='json')

    def allocation(self, *, per_meal_cap=None, priority=100):
        return SponsorshipAllocation.objects.create(
            fund=self.fund, student=self.student, meal_types=['lunch'],
            daily_cap=Decimal('150.00'), per_meal_cap=Decimal(per_meal_cap) if per_meal_cap else None,
            valid_from=date.today(), priority=priority,
        )

    def scan(self):
        session = ScanSession.objects.create(operator=self.operator, type='lunch')
        return self.operator_api.post('/api/v1/sessions/scan-card', {
            'session_id': str(session.id), 'card_number': self.card.card_number,
            'item_id': str(self.item.id),
        }, format='json')

    def test_fund_contribution_and_close_refund_are_audited(self):
        self.assertEqual(self.contribute().status_code, 201)
        closed = self.admin_api.post(f'/api/v1/sponsorship/funds/{self.fund.pk}/close', {
            'disposition': 'refund', 'reason': 'Programme ended',
        }, format='json')
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertEqual(closed.data['status'], 'closed')
        self.assertEqual(closed.data['balance'], '0.00')
        self.assertGreaterEqual(AuditLog.objects.count(), 2)

    def test_close_transfer_moves_remaining_balance(self):
        self.contribute('125.00')
        target = SponsorFund.objects.create(name='Target Fund', sponsor_name='Other', start_date=date.today())
        closed = self.admin_api.post(f'/api/v1/sponsorship/funds/{self.fund.pk}/close', {
            'disposition': 'transfer', 'target_fund_id': target.pk, 'reason': 'Consolidation',
        }, format='json')
        self.assertEqual(closed.status_code, 200, closed.data)
        target_lines = target.journal_lines.filter(account__code='2200')
        self.assertEqual(sum(target_lines.filter(direction='credit').values_list('amount', flat=True), Decimal('0.00')), Decimal('125.00'))

    def test_allocation_bulk_dry_run_then_create(self):
        payload = {
            'mode': 'student_ids', 'fund_id': self.fund.pk,
            'student_ids': [str(self.student.pk)], 'meal_types': ['lunch'],
            'valid_from': date.today().isoformat(), 'daily_cap': '100.00', 'dry_run': True,
        }
        result = self.admin_api.post('/api/v1/sponsorship/allocations/bulk', payload, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data['valid'], 1)
        self.assertEqual(SponsorshipAllocation.objects.count(), 0)
        payload['dry_run'] = False
        result = self.admin_api.post('/api/v1/sponsorship/allocations/bulk', payload, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(SponsorshipAllocation.objects.count(), 1)

    def test_bulk_invalid_row_is_all_or_nothing(self):
        payload = {
            'mode': 'student_ids', 'fund_id': self.fund.pk,
            'student_ids': [str(self.student.pk), '00000000-0000-0000-0000-000000000000'],
            'meal_types': ['lunch'], 'valid_from': date.today().isoformat(), 'dry_run': False,
        }
        result = self.admin_api.post('/api/v1/sponsorship/allocations/bulk', payload, format='json')
        self.assertEqual(result.status_code, 400)
        self.assertEqual(SponsorshipAllocation.objects.count(), 0)

    def test_scan_waterfall_then_reversal_restores_fund_and_wallet(self):
        self.assertEqual(self.contribute().status_code, 201)
        self.allocation()
        response = self.scan()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['payment_breakdown'][0]['source'], 'fund')
        self.assertEqual(response.data['payment_breakdown'][0]['amount'], '100.00')
        txn = Transaction.objects.get()
        self.assertEqual(txn.charged_amount, Decimal('0.00'))
        self.assertEqual(sum(TransactionPayment.objects.filter(transaction=txn).values_list('amount', flat=True), Decimal('0.00')), Decimal('100.00'))
        reversed_response = self.admin_api.post('/api/v1/wallet/transaction/reverse', {
            'transaction_id': str(txn.id), 'reason': 'Wrong meal entry',
        }, format='json')
        self.assertEqual(reversed_response.status_code, 200, reversed_response.data)
        self.assertEqual(self.card.__class__.objects.get(pk=self.card.pk).balance, Decimal('500.00'))
        lines = list(self.fund.journal_lines.filter(account__code='2200').values('direction', 'amount'))
        credits = sum((row['amount'] for row in lines if row['direction'] == 'credit'), Decimal('0.00'))
        debits = sum((row['amount'] for row in lines if row['direction'] == 'debit'), Decimal('0.00'))
        self.assertEqual(credits - debits, Decimal('500.00'))

    def test_partial_fund_share_charges_only_wallet_remainder(self):
        self.assertEqual(self.contribute('40.00').status_code, 201)
        self.allocation(per_meal_cap='40.00')
        response = self.scan()
        self.assertEqual(response.status_code, 201, response.data)
        txn = Transaction.objects.get()
        self.card.refresh_from_db()
        self.assertEqual(txn.charged_amount, Decimal('60.00'))
        self.assertEqual(self.card.balance, Decimal('440.00'))
        self.assertEqual(sum(TransactionPayment.objects.filter(transaction=txn).values_list('amount', flat=True), Decimal('0.00')), Decimal('100.00'))
        self.assertEqual([part['source'] for part in response.data['payment_breakdown']], ['fund', 'wallet'])

    def test_report_hides_student_name_by_default(self):
        self.contribute('100.00')
        self.allocation()
        self.scan()
        response = self.admin_api.get(f'/api/v1/sponsorship/funds/{self.fund.pk}/report')
        self.assertEqual(response.status_code, 200, response.data)
        student = response.data['students'][0]
        self.assertEqual(student['student'], f"S-{int(str(self.student.pk).replace('-', ''), 16) % 10000000:07d}")
        self.assertNotIn('student_name', student)

    def test_analytics_counts_sponsor_payment_as_meal_revenue(self):
        FeatureFlag.objects.update_or_create(key='ANALYTICS', defaults={'enabled': True})
        self.contribute('100.00')
        self.allocation()
        self.assertEqual(self.scan().status_code, 201)
        day = date.today().isoformat()
        result = self.admin_api.get('/api/v1/analytics/sales', {'from': day, 'to': day})
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data['totals']['revenue'], Decimal('100.00'))

    def test_low_fund_alert_is_deduplicated(self):
        self.fund.alert_threshold = Decimal('20.00')
        self.fund.save(update_fields=['alert_threshold'])
        from smmsapp.tasks import check_sponsor_funds
        self.assertEqual(check_sponsor_funds(), 1)
        self.assertEqual(check_sponsor_funds(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.admin, dedupe_key__startswith='sponsor-fund:').count(), 1)
        self.assertEqual(InsightFlag.objects.filter(kind='fund_empty').count(), 1)

    def test_parent_cannot_view_any_fund(self):
        self.assertEqual(self.parent_api.get('/api/v1/sponsorship/funds').status_code, 403)

