from decimal import Decimal

from django.db.models import Q, Sum

from smmsapp.models import JournalLine, SponsorshipAllocation, TransactionPayment


def has_eligible_allocation(student, meal_type, on_date):
    rows = SponsorshipAllocation.objects.filter(
        student=student, is_active=True, fund__status='active', valid_from__lte=on_date,
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on_date)).only('meal_types')
    return any(meal_type in row.meal_types for row in rows)


def allocate_sponsor_shares(student, meal_type, on_date, amount):
    """Return priority-ordered fund shares, locking funds in stable ID order."""
    remaining = Decimal(amount)
    allocations = list(SponsorshipAllocation.objects.filter(
        student=student, is_active=True, fund__status='active',
        valid_from__lte=on_date,
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on_date)).select_related('fund').order_by('priority', 'fund_id'))
    fund_ids = sorted({row.fund_id for row in allocations})
    from smmsapp.models import SponsorFund
    funds = {row.pk: row for row in SponsorFund.objects.select_for_update().filter(pk__in=fund_ids).order_by('id')}
    shares = []
    for allocation in allocations:
        if meal_type not in allocation.meal_types:
            continue
        if remaining <= 0:
            break
        fund = funds.get(allocation.fund_id)
        if fund is None or fund.status != 'active':
            continue
        ledger = JournalLine.objects.filter(fund=fund, account__code='2200').aggregate(
            credit=Sum('amount', filter=Q(direction='credit')),
            debit=Sum('amount', filter=Q(direction='debit')),
        )
        balance = (ledger['credit'] or Decimal('0.00')) - (ledger['debit'] or Decimal('0.00'))
        take = min(remaining, balance)
        if allocation.per_meal_cap is not None:
            spent = TransactionPayment.objects.filter(
                fund=fund, transaction__student_or_staff=student,
                transaction__session__type=meal_type, transaction__transaction_date__date=on_date,
                transaction__is_voided=False,
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            take = min(take, max(Decimal('0.00'), allocation.per_meal_cap - spent))
        if allocation.daily_cap is not None:
            spent = TransactionPayment.objects.filter(
                fund=fund, transaction__student_or_staff=student,
                transaction__transaction_date__date=on_date, transaction__is_voided=False,
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            take = min(take, max(Decimal('0.00'), allocation.daily_cap - spent))
        if take > 0:
            shares.append((fund, take))
            remaining -= take
    return shares
