from decimal import Decimal

from django.db.models import F, Sum

from smmsapp.models import Reconciliation, Transaction


def session_summary(session):
    transactions = Transaction.objects.filter(session=session, is_voided=False)
    scanned_value = transactions.filter(transaction_status='successful').aggregate(
        total=Sum('item__price'),
    )['total'] or Decimal('0.00')
    penalty_value = transactions.filter(transaction_status='penalty').aggregate(
        total=Sum(F('amount') - F('item__price')),
    )['total'] or Decimal('0.00')
    reconciliation = Reconciliation.objects.filter(session=session).first()
    expected_cash = reconciliation.expected_cash if reconciliation else Decimal('0.00')
    variance = expected_cash - scanned_value
    return {
        'scanned_value': scanned_value,
        'penalty_value': penalty_value,
        'expected_cash': expected_cash,
        'variance': variance,
        'status': reconciliation.status if reconciliation else session.status,
    }
