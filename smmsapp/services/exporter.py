import csv
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from ..models import (
    BankDeposit, CustomUser, CanteenItem, ParentStudent, RFIDCard,
    Reconciliation, Reversal, ScanSession, Transaction,
)
from .alerts import _effective_threshold
from ..utils import get_admin_scope

EXPORT_SYNC_MAX_ROWS = getattr(settings, 'EXPORT_SYNC_MAX_ROWS', 2000)


# ---------------------------------------------------------------------------
# Role-scoped queryset builders (mirror the list views' filtering
# ---------------------------------------------------------------------------

def transaction_queryset(user, filters):
    qs = Transaction.objects.prefetch_related('payment_parts__fund').all().order_by('-transaction_date')

    school = get_admin_scope(user)
    if user.role == 'admin':
        if school is not None:
            qs = qs.filter(student_or_staff__school=school)
    elif user.role == 'parent':
        from ..models import ParentStudent
        children = ParentStudent.objects.filter(parent=user).values_list('student_id', flat=True)
        qs = qs.filter(student_or_staff_id__in=list(children))
    elif user.role == 'staff':
        qs = qs.filter(student_or_staff=user)
    elif user.role == 'operator':
        qs = qs.filter(session__operator=user)
    else:
        qs = qs.none()

    return _apply_transaction_filters(qs, filters)


def _apply_transaction_filters(qs, filters):
    from_date = filters.get('from_date')
    to_date = filters.get('to_date')
    status_val = (filters.get('status') or '').strip()
    search = (filters.get('search') or '').strip()

    if from_date:
        qs = qs.filter(transaction_date__date__gte=from_date)
    if to_date:
        qs = qs.filter(transaction_date__date__lte=to_date)
    if status_val:
        qs = qs.filter(transaction_status=status_val)
    if search:
        qs = qs.filter(
            Q(student_or_staff__username__icontains=search) |
            Q(student_or_staff__first_name__icontains=search) |
            Q(student_or_staff__last_name__icontains=search) |
            Q(rfid_card__card_number__icontains=search)
        )
    return qs


def student_queryset(user, filters):
    qs = CustomUser.objects.filter(role='student').order_by('first_name')

    school = get_admin_scope(user)
    if user.role == 'admin':
        if school is not None:
            qs = qs.filter(school=school)
    elif user.role == 'parent':
        from ..models import ParentStudent
        qs = qs.filter(parents__parent=user)
    else:
        qs = qs.filter(id=user.id)

    search = (filters.get('search') or '').strip()
    class_room = (filters.get('class_room') or '').strip()
    active = filters.get('active')

    if search:
        qs = qs.filter(
            Q(username__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(mobile_number__icontains=search)
        )
    if class_room:
        qs = qs.filter(class_room__icontains=class_room)
    if active is not None:
        qs = qs.filter(is_active=active)
    return qs


def deposit_queryset(user, filters):
    qs = BankDeposit.objects.all().order_by('-created_at')

    school = get_admin_scope(user)
    if user.role in ('admin', 'operator'):
        if school is not None:
            qs = qs.filter(control_number__student_or_staff__school=school)
    elif user.role == 'parent':
        qs = qs.filter(submitted_by=user)
    else:
        qs = qs.none()

    from_date = filters.get('from_date')
    to_date = filters.get('to_date')
    status_val = (filters.get('status') or '').strip()

    if from_date:
        qs = qs.filter(created_at__date__gte=from_date)
    if to_date:
        qs = qs.filter(created_at__date__lte=to_date)
    if status_val:
        qs = qs.filter(status=status_val)
    return qs


# ---------------------------------------------------------------------------
# Row builders -> list of scalar values aligned with headers
# ---------------------------------------------------------------------------

def _transaction_rows(qs):
    rows = []
    for t in qs.select_related('student_or_staff', 'item'):
        parts = list(t.payment_parts.all())
        gross = sum((part.amount for part in parts), Decimal('0.00')) if parts else t.charged_amount
        fund_paid = sum((part.amount for part in parts if part.source == 'fund'), Decimal('0.00'))
        rows.append([
            t.id,
            t.student_or_staff.username,
            f"{t.student_or_staff.first_name} {t.student_or_staff.last_name}".strip(),
            t.rfid_card.card_number,
            t.item.name if t.item else '',
            t.charged_amount,
            gross,
            fund_paid,
            t.transaction_status,
            t.transaction_date.isoformat() if t.transaction_date else '',
            'Voided' if t.is_voided else '',
        ])
    return rows


def _student_rows(qs):
    rows = []
    for s in qs.select_related('school'):
        card = s.rfid_cards.filter(is_active=True).first()
        rows.append([
            s.username,
            s.first_name,
            s.last_name,
            s.class_room or '',
            s.school.name if s.school else '',
            s.mobile_number or '',
            card.balance if card else '',
            'Active' if s.is_active else 'Inactive',
        ])
    return rows


def _deposit_rows(qs):
    rows = []
    for d in qs.select_related('control_number', 'submitted_by'):
        rows.append([
            d.control_number.card_number,
            d.amount,
            d.status,
            d.created_at.date().isoformat() if d.created_at else '',
            d.processed_at.date().isoformat() if d.processed_at else '',
            d.submitted_by.username if d.submitted_by else '',
        ])
    return rows


def _analytics_dates(filters):
    today = timezone.localdate()
    start = filters.get('from_date') or (today - timedelta(days=settings.ANALYTICS_DEFAULT_RANGE_DAYS - 1))
    end = filters.get('to_date') or today
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if isinstance(end, str):
        end = date.fromisoformat(end)
    return start, end


def _analytics_txns(user, filters):
    start, end = _analytics_dates(filters)
    qs = Transaction.objects.filter(
        transaction_date__date__gte=start, transaction_date__date__lte=end,
        transaction_status__in=['successful', 'penalty'], is_voided=False,
    )
    school = get_admin_scope(user)
    if school is not None:
        qs = qs.filter(student_or_staff__school=school)
    from .transaction_metrics import with_payment_revenue
    return with_payment_revenue(qs)


def analytics_sales_queryset(user, filters):
    from .transaction_metrics import penalty_charge_expression
    return list(_analytics_txns(user, filters).annotate(day=TruncDate('transaction_date')).values('day').annotate(
        revenue=Sum('payment_revenue', filter=Q(transaction_status='successful')),
        penalty=Sum(penalty_charge_expression(), filter=Q(transaction_status='penalty')),
        meals=Count('id'),
    ).order_by('day'))


def _analytics_sales_rows(rows):
    return [[r['day'].isoformat(), r['revenue'] or Decimal('0.00'), r['meals'], r['penalty'] or Decimal('0.00')] for r in rows]


def analytics_wallet_health_queryset(user, filters):
    cards = RFIDCard.objects.filter(is_active=True).select_related('student_or_staff')
    school = get_admin_scope(user)
    if school is not None:
        cards = cards.filter(student_or_staff__school=school)
    card_rows = list(cards)
    parent_links = ParentStudent.objects.filter(student_id__in=[c.student_or_staff_id for c in card_rows]).select_related('parent')
    thresholds = {}
    for link in parent_links:
        thresholds.setdefault(link.student_id, []).append(_effective_threshold(link.parent))
    summary = {
        'float_total': sum((c.balance for c in card_rows), Decimal('0.00')),
        'avg_balance': sum((c.balance for c in card_rows), Decimal('0.00')) / len(card_rows) if card_rows else Decimal('0.00'),
        'below_threshold': sum(1 for c in card_rows if any(c.balance < threshold for threshold in thresholds.get(c.student_or_staff_id, []))),
        'at_floor': sum(1 for c in card_rows if c.balance <= Decimal(str(settings.RFID_BALANCE_FLOOR))),
        'near_strike_limit': sum(1 for c in card_rows if c.insufficient_meal_count >= settings.STRIKE_LIMIT - 2),
    }
    start, end = _analytics_dates(filters)
    deposits = BankDeposit.objects.filter(status='processed', processed_at__date__gte=start, processed_at__date__lte=end)
    spends = _analytics_txns(user, filters)
    if school is not None:
        deposits = deposits.filter(control_number__student_or_staff__school=school)
    deposits_by_day = {r['day']: r['total'] for r in deposits.annotate(day=TruncDate('processed_at')).values('day').annotate(total=Sum('amount'))}
    spends_by_day = {r['day']: r['total'] for r in spends.annotate(day=TruncDate('transaction_date')).values('day').annotate(total=Sum('payment_revenue'))}
    daily_rows = []
    current = start
    while current <= end:
        daily_rows.append((current, deposits_by_day.get(current, Decimal('0.00')), spends_by_day.get(current, Decimal('0.00'))))
        current += timedelta(days=1)
    return {'summary': summary, 'daily': daily_rows}


def _analytics_wallet_rows(data):
    summary = data['summary']
    rows = [
        ['summary', '', 'float_total', summary['float_total'], ''],
        ['summary', '', 'avg_balance', summary['avg_balance'], ''],
        ['summary', '', 'below_threshold', '', summary['below_threshold']],
        ['summary', '', 'at_floor', '', summary['at_floor']],
        ['summary', '', 'near_strike_limit', '', summary['near_strike_limit']],
    ]
    rows.extend([['daily', day.isoformat(), '', deposits, spend] for day, deposits, spend in data['daily']])
    return rows


def analytics_operators_queryset(user, filters):
    start, end = _analytics_dates(filters)
    operators = CustomUser.objects.filter(role='operator').order_by('last_name', 'first_name')
    school = get_admin_scope(user)
    if school is not None:
        operators = operators.filter(school=school)
    rows = []
    for operator in operators:
        sessions = ScanSession.objects.filter(operator=operator, start_at__date__gte=start, start_at__date__lte=end)
        session_ids = sessions.values('id')
        totals = Transaction.objects.filter(
            session_id__in=session_ids, transaction_date__date__gte=start, transaction_date__date__lte=end,
            transaction_status='successful', is_voided=False,
        ).aggregate(revenue=Sum('payment_revenue'))
        variance = Reconciliation.objects.filter(session_id__in=session_ids).aggregate(total=Sum('variance'))['total']
        reversal_count = Reversal.objects.filter(transaction__session__operator=operator, reversed_at__date__gte=start, reversed_at__date__lte=end).count()
        rows.append({
            'operator': f'{operator.first_name} {operator.last_name}'.strip() or operator.username,
            'sessions': sessions.count(), 'revenue': totals['revenue'] or Decimal('0.00'),
            'variance': variance or Decimal('0.00'), 'reversals': reversal_count,
        })
    return rows


def sponsorship_report_queryset(user, filters):
    from ..models import TransactionPayment
    qs = TransactionPayment.objects.filter(
        fund_id=filters.get('fund_id'), transaction__transaction_status__in=['successful', 'penalty'],
        transaction__is_voided=False,
    ).select_related('transaction__student_or_staff', 'transaction__session').order_by('transaction__transaction_date')
    start, end = _analytics_dates(filters)
    qs = qs.filter(transaction__transaction_date__date__gte=start, transaction__transaction_date__date__lte=end)
    school = get_admin_scope(user)
    if school is not None:
        qs = qs.filter(transaction__student_or_staff__school=school)
    return qs


def _sponsorship_report_rows(qs, filters):
    grouped = {}
    hide_names = filters.get('hide_names', True)
    for part in qs:
        student = part.transaction.student_or_staff
        student_code = f'S-{int(str(student.pk).replace("-", ""), 16) % 10000000:07d}'
        row = grouped.setdefault(str(student.pk), {
            'student': student_code if hide_names else f'{student.first_name} {student.last_name}'.strip(),
            'class_room': student.class_room or '', 'meals': set(), 'amount': Decimal('0.00'),
        })
        row['meals'].add(part.transaction_id)
        row['amount'] += part.amount
    return [[row['student'], row['class_room'], len(row['meals']), row['amount']]
            for _, row in sorted(grouped.items())]


def _analytics_operator_rows(rows):
    return [[r['operator'], r['sessions'], r['revenue'], r['variance'], r['reversals']] for r in rows]


TRANSACTION_HEADERS = [
    'Transaction ID', 'Username', 'Name', 'Card Number', 'Item', 'Wallet Charged', 'Meal Revenue', 'Sponsor Paid',
    'Status', 'Transaction Date', 'Voided',
]
STUDENT_HEADERS = [
    'Username', 'First Name', 'Last Name', 'Class Room', 'School', 'Mobile',
    'Balance', 'Status',
]
DEPOSIT_HEADERS = [
    'Card Number', 'Amount', 'Status', 'Created Date', 'Processed Date', 'Submitted By',
]

ENTITY_BUILDERS = {
    'transactions': (transaction_queryset, _transaction_rows, TRANSACTION_HEADERS),
    'students': (student_queryset, _student_rows, STUDENT_HEADERS),
    'deposits': (deposit_queryset, _deposit_rows, DEPOSIT_HEADERS),
    'analytics_sales': (analytics_sales_queryset, _analytics_sales_rows, ['Date', 'Revenue', 'Meals', 'Penalty Amount']),
    'analytics_wallet_health': (analytics_wallet_health_queryset, _analytics_wallet_rows, ['Record Type', 'Date', 'Metric', 'Deposits or Value', 'Spend or Count']),
    'analytics_operators': (analytics_operators_queryset, _analytics_operator_rows, ['Operator', 'Sessions', 'Revenue', 'Variance', 'Reversals']),
    'sponsorship_fund_report': (sponsorship_report_queryset, _sponsorship_report_rows, ['Student', 'Class', 'Meals', 'Sponsored Amount']),
}


# ---------------------------------------------------------------------------
# Serializers to bytes (CSV / xlsx)
# ---------------------------------------------------------------------------

def export_to_csv(rows, headers):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    buffer.seek(0)
    return buffer.getvalue().encode('utf-8-sig')


def export_to_xlsx(rows, headers):
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)

    for idx, _ in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = 22

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
