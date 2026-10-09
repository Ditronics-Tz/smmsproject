from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from rest_framework.test import APIClient

from smmsapp.models import CanteenItem, JournalEntry, LedgerEntry, RFIDCard, ScanSession, School
from smmsapp.services.legacy_ledger import record_legacy_ledger_entry


User = get_user_model()


class LegacyLedgerToggleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        school = School.objects.create(name='Legacy ledger toggle school')
        student = User.objects.create_user(
            username='legacy-ledger-student', role='student', school=school,
        )
        cls.card = RFIDCard.objects.create(
            card_number='LEGACY-LEDGER-CARD', control_number='LEGACY-LEDGER-CONTROL',
            student_or_staff=student, balance=Decimal('100.00'),
        )
        cls.operator = User.objects.create_user(
            username='legacy-ledger-operator', role='operator', school=school,
        )
        cls.item = CanteenItem.objects.create(name='Legacy toggle meal', price=Decimal('10.00'))
        cls.session = ScanSession.objects.create(operator=cls.operator, type='lunch', status='active')

    def entry_fields(self):
        return {
            'rfid_card': self.card,
            'event_type': 'deposit',
            'amount': Decimal('10.00'),
            'balance_before': Decimal('0.00'),
            'balance_after': Decimal('10.00'),
        }

    @override_settings(LEDGER_LEGACY_WRITE=True)
    def test_default_cutover_mode_keeps_the_legacy_write(self):
        entry = record_legacy_ledger_entry(**self.entry_fields())
        self.assertIsNotNone(entry)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    @override_settings(LEDGER_LEGACY_WRITE=False)
    def test_disabled_legacy_write_does_not_create_old_ledger_rows(self):
        self.assertIsNone(record_legacy_ledger_entry(**self.entry_fields()))
        self.assertEqual(LedgerEntry.objects.count(), 0)

    @override_settings(LEDGER_LEGACY_WRITE=False)
    def test_journal_posts_continue_after_legacy_dual_write_is_disabled(self):
        api = APIClient()
        api.force_authenticate(self.operator)
        response = api.post('/api/v1/sessions/scan-card', {
            'session_id': str(self.session.id), 'card_number': self.card.card_number,
            'item_id': str(self.item.id),
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(LedgerEntry.objects.count(), 0)
        self.assertTrue(JournalEntry.objects.exists())
