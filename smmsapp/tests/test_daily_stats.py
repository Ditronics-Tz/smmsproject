from datetime import datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from smmsapp.models import (
    BankDeposit, CanteenItem, DailyStats, RFIDCard, Reconciliation,
    Reversal, ScanSession, School, Transaction,
)
from smmsapp.services.analytics import build_daily_stats_for_day

User = get_user_model()


class DailyStatsTests(TestCase):
    def test_snapshot_matches_live_aggregates_and_is_idempotent(self):
        day = timezone.localdate()
        event_time = timezone.make_aware(datetime.combine(day, time(12, 0)))
        school = School.objects.create(name='Daily Stats School')
        operator = User.objects.create_user(username='stats-operator', role='operator', school=school)
        student = User.objects.create_user(username='stats-student', role='student', school=school)
        card = RFIDCard.objects.create(card_number='STATS-CARD', control_number='STATS-CTRL', student_or_staff=student)
        item = CanteenItem.objects.create(name='Stats Meal', price=Decimal('100.00'))
        session = ScanSession.objects.create(operator=operator, type='lunch')
        ScanSession.objects.filter(pk=session.pk).update(start_at=event_time)

        successful = Transaction.objects.create(
            student_or_staff=student, rfid_card=card, item=item, session=session,
            amount=Decimal('100'), charged_amount=Decimal('100'), transaction_status='successful',
        )
        penalty = Transaction.objects.create(
            student_or_staff=student, rfid_card=card, item=item, session=session,
            amount=Decimal('120'), charged_amount=Decimal('20'), transaction_status='penalty',
        )
        reversed_txn = Transaction.objects.create(
            student_or_staff=student, rfid_card=card, item=item, session=session,
            amount=Decimal('100'), charged_amount=Decimal('100'), transaction_status='successful', is_voided=True,
        )
        Reversal.objects.create(transaction=reversed_txn, reason='mistake')
        BankDeposit.objects.create(
            control_number=card, amount=Decimal('250'), status='processed', processed_at=event_time,
        )
        Reconciliation.objects.create(
            session=session, scanned_value=Decimal('100'), expected_cash=Decimal('90'),
            variance=Decimal('-10'), status='variance',
        )
        Transaction.objects.filter(pk__in=[successful.pk, penalty.pk, reversed_txn.pk]).update(transaction_date=event_time)
        Reversal.objects.filter(transaction=reversed_txn).update(reversed_at=event_time)

        self.assertEqual(build_daily_stats_for_day(day), 4)  # breakfast, lunch, dinner, all
        stats = DailyStats.objects.get(date=day, meal_type='lunch')
        self.assertEqual(stats.revenue, Decimal('100.00'))
        self.assertEqual(stats.penalty_amount, Decimal('20.00'))
        self.assertEqual(stats.meals, 2)
        self.assertEqual(stats.unique_students, 1)
        self.assertEqual(stats.reversals, 1)
        self.assertEqual(stats.variance_total, Decimal('-10.00'))
        all_stats = DailyStats.objects.get(date=day, meal_type='all')
        self.assertEqual(all_stats.deposits_amount, Decimal('250.00'))
        self.assertEqual(all_stats.meals, 2)

        self.assertEqual(build_daily_stats_for_day(day), 4)
        self.assertEqual(DailyStats.objects.filter(date=day).count(), 4)
