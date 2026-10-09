from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, Q, Sum

from smmsapp.models import (
    BankDeposit, DailyStats, Reconciliation, Reversal, ScanSession, Transaction,
)


def build_daily_stats_for_day(day):
    """Rebuild one daily snapshot idempotently, including an all-meals row."""
    rows = []
    meal_types = [choice[0] for choice in ScanSession.SESSION_TYPE_CHOICES]
    for meal_type in meal_types:
        transactions = Transaction.objects.filter(
            transaction_date__date=day,
            session__type=meal_type,
            transaction_status__in=['successful', 'penalty'],
            is_voided=False,
        )
        from .transaction_metrics import penalty_charge_expression, with_payment_revenue
        transactions = with_payment_revenue(transactions)
        totals = transactions.aggregate(
            revenue=Sum('payment_revenue', filter=Q(transaction_status='successful')),
            penalty_amount=Sum(penalty_charge_expression(), filter=Q(transaction_status='penalty')),
            meals=Count('id'),
            unique_students=Count('student_or_staff_id', distinct=True),
        )
        session_ids = ScanSession.objects.filter(start_at__date=day, type=meal_type).values('id')
        variance = Reconciliation.objects.filter(session_id__in=session_ids).aggregate(total=Sum('variance'))['total'] or Decimal('0.00')
        reversals = Reversal.objects.filter(
            reversed_at__date=day,
            transaction__session__type=meal_type,
        ).count()
        values = {
            'revenue': totals['revenue'] or Decimal('0.00'),
            'penalty_amount': totals['penalty_amount'] or Decimal('0.00'),
            'meals': totals['meals'] or 0,
            'unique_students': totals['unique_students'] or 0,
            'deposits_amount': Decimal('0.00'),
            'reversals': reversals,
            'variance_total': variance,
        }
        DailyStats.objects.update_or_create(date=day, meal_type=meal_type, defaults=values)
        rows.append(values)

    deposits = BankDeposit.objects.filter(
        status='processed', processed_at__date=day,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    all_values = {
        key: sum((row[key] for row in rows), Decimal('0.00') if key in ('revenue', 'penalty_amount', 'deposits_amount', 'variance_total') else 0)
        for key in ('revenue', 'penalty_amount', 'meals', 'unique_students', 'deposits_amount', 'reversals', 'variance_total')
    }
    all_values['unique_students'] = Transaction.objects.filter(
        transaction_date__date=day, transaction_status__in=['successful', 'penalty'], is_voided=False,
    ).values('student_or_staff_id').distinct().count()
    all_values['deposits_amount'] = deposits
    DailyStats.objects.update_or_create(date=day, meal_type='all', defaults=all_values)

    # Versioned keys let this work with both local-memory and Redis cache backends.
    cache_version_key = 'analytics:cache-version'
    current = cache.get(cache_version_key, 0)
    cache.set(cache_version_key, current + 1, timeout=None)
    return len(rows) + 1
