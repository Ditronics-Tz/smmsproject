import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncHour
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from smmsapp.models import (
    BankDeposit, CustomUser, DailyStats, ParentStudent, RFIDCard, Reconciliation,
    Reversal, ScanSession, ScannedData, Transaction,
)
from smmsapp.permissions.features import FeatureEnabled
from smmsapp.permissions.roles import IsAdminOnly
from smmsapp.services.alerts import _effective_threshold
from smmsapp.utils import get_admin_scope


def _date_range(request, *, default_days=None):
    default_days = default_days or settings.ANALYTICS_DEFAULT_RANGE_DAYS
    today = timezone.localdate()
    try:
        end = date.fromisoformat(request.query_params.get('to', today.isoformat()))
        start = date.fromisoformat(request.query_params.get('from', (today - timedelta(days=default_days - 1)).isoformat()))
    except ValueError:
        return None, None, Response({'code': 'INVALID_DATE_RANGE', 'detail': 'Dates must use YYYY-MM-DD.'}, status=400)
    if start > end:
        return None, None, Response({'code': 'INVALID_DATE_RANGE', 'detail': '`from` must be on or before `to`.'}, status=400)
    if (end - start).days >= settings.ANALYTICS_MAX_RANGE_DAYS:
        return None, None, Response({'code': 'INVALID_DATE_RANGE', 'detail': f'Date range may not exceed {settings.ANALYTICS_MAX_RANGE_DAYS} days.'}, status=400)
    return start, end, None


def _scope(request, queryset):
    school = get_admin_scope(request.user)
    if school is not None:
        return queryset.filter(student_or_staff__school=school)
    return queryset


def _cached(request, name, filters, builder):
    raw = json.dumps({
        'name': name,
        'school': str(get_admin_scope(request.user).id) if get_admin_scope(request.user) else 'global',
        'filters': filters,
        'version': cache.get('analytics:cache-version', 0),
    }, sort_keys=True, default=str)
    key = 'analytics:' + hashlib.sha256(raw.encode()).hexdigest()
    data = cache.get(key)
    if data is None:
        data = builder()
        cache.set(key, data, timeout=300)
    response = Response(data)
    response['Cache-Control'] = 'private, max-age=300'
    return response


def _transactions(start, end, request, *, meal_type=None):
    qs = Transaction.objects.filter(
        transaction_date__date__gte=start,
        transaction_date__date__lte=end,
        transaction_status__in=['successful', 'penalty'],
        is_voided=False,
    ).select_related('student_or_staff', 'item', 'session')
    qs = _scope(request, qs)
    if meal_type:
        qs = qs.filter(session__type=meal_type)
    return qs


def _money(value):
    return value or Decimal('0.00')


@extend_schema(
    tags=['analytics'],
    parameters=[
        OpenApiParameter('from', OpenApiTypes.DATE), OpenApiParameter('to', OpenApiTypes.DATE),
        OpenApiParameter('meal_type', OpenApiTypes.STR),
        OpenApiParameter('group_by', OpenApiTypes.STR, enum=['day', 'item', 'hour']),
    ],
    responses=OpenApiTypes.OBJECT,
)
class SalesAnalyticsView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('ANALYTICS')]

    def get(self, request):
        start, end, error = _date_range(request)
        if error:
            return error
        group_by = request.query_params.get('group_by', 'day')
        meal_type = request.query_params.get('meal_type') or None
        if group_by not in ('day', 'item', 'hour'):
            return Response({'group_by': ['Use day, item, or hour.']}, status=400)
        filters = {'from': start.isoformat(), 'to': end.isoformat(), 'meal_type': meal_type, 'group_by': group_by}

        def build():
            qs = _transactions(start, end, request, meal_type=meal_type)
            totals = qs.aggregate(
                revenue=Sum('charged_amount', filter=Q(transaction_status='successful')),
                penalty_amount=Sum('charged_amount', filter=Q(transaction_status='penalty')),
                count=Count('id'),
            )
            if group_by == 'day':
                live = {
                    row['day'].isoformat(): row for row in qs.annotate(day=TruncDate('transaction_date')).values('day').annotate(
                        revenue=Sum('charged_amount', filter=Q(transaction_status='successful')),
                        penalty_amount=Sum('charged_amount', filter=Q(transaction_status='penalty')),
                        count=Count('id'),
                    )
                }
                use_daily = get_admin_scope(request.user) is None
                snapshots = {}
                if use_daily:
                    snapshots = {
                        row.date.isoformat(): row for row in DailyStats.objects.filter(
                            date__gte=start, date__lte=min(end, timezone.localdate() - timedelta(days=1)),
                            meal_type=meal_type or 'all',
                        )
                    }
                series = []
                day = start
                today = timezone.localdate()
                while day <= end:
                    key = day.isoformat()
                    snap = snapshots.get(key) if day < today else None
                    live_row = live.get(key)
                    if snap:
                        revenue, penalty, count = snap.revenue, snap.penalty_amount, snap.meals
                    elif live_row:
                        revenue = _money(live_row['revenue'])
                        penalty = _money(live_row['penalty_amount'])
                        count = live_row['count']
                    else:
                        revenue, penalty, count = Decimal('0.00'), Decimal('0.00'), 0
                    series.append({'label': key, 'revenue': revenue, 'count': count, 'penalty_amount': penalty})
                    day += timedelta(days=1)
            elif group_by == 'item':
                rows = qs.values('item__name').annotate(
                    revenue=Sum('charged_amount', filter=Q(transaction_status='successful')),
                    penalty_amount=Sum('charged_amount', filter=Q(transaction_status='penalty')),
                    count=Count('id'),
                ).order_by('item__name')
                series = [{'label': r['item__name'], 'revenue': _money(r['revenue']), 'penalty_amount': _money(r['penalty_amount']), 'count': r['count']} for r in rows]
            else:
                rows = qs.annotate(hour=TruncHour('transaction_date', tzinfo=timezone.get_current_timezone())).values('hour').annotate(
                    revenue=Sum('charged_amount', filter=Q(transaction_status='successful')),
                    penalty_amount=Sum('charged_amount', filter=Q(transaction_status='penalty')),
                    count=Count('id'),
                ).order_by('hour')
                series = [{'label': r['hour'].isoformat(), 'revenue': _money(r['revenue']), 'penalty_amount': _money(r['penalty_amount']), 'count': r['count']} for r in rows]
            return {
                'series': series,
                'totals': {'revenue': _money(totals['revenue']), 'count': totals['count'] or 0, 'penalty_amount': _money(totals['penalty_amount'])},
            }

        return _cached(request, 'sales', filters, build)


@extend_schema(tags=['analytics'], responses=OpenApiTypes.OBJECT)
class WalletHealthView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('ANALYTICS')]

    def get(self, request):
        def build():
            cards = RFIDCard.objects.filter(is_active=True).select_related('student_or_staff')
            school = get_admin_scope(request.user)
            if school is not None:
                cards = cards.filter(student_or_staff__school=school)
            card_rows = list(cards)
            thresholds = {}
            links = ParentStudent.objects.filter(student_id__in=[c.student_or_staff_id for c in card_rows]).select_related('parent')
            for link in links:
                thresholds.setdefault(link.student_id, []).append(_effective_threshold(link.parent))
            below = sum(1 for card in card_rows if any(card.balance < value for value in thresholds.get(card.student_or_staff_id, [])))
            today = timezone.localdate()
            first = today - timedelta(days=settings.ANALYTICS_DEFAULT_RANGE_DAYS - 1)
            deposits = BankDeposit.objects.filter(status='processed', processed_at__date__gte=first, processed_at__date__lte=today)
            if school is not None:
                deposits = deposits.filter(control_number__student_or_staff__school=school)
            deposit_rows = {r['day'].isoformat(): r['total'] for r in deposits.annotate(day=TruncDate('processed_at')).values('day').annotate(total=Sum('amount'))}
            spend_qs = Transaction.objects.filter(
                transaction_date__date__gte=first, transaction_date__date__lte=today,
                transaction_status__in=['successful', 'penalty'], is_voided=False,
            )
            spend_qs = _scope(request, spend_qs)
            spend_rows = {r['day'].isoformat(): r['total'] for r in spend_qs.annotate(day=TruncDate('transaction_date')).values('day').annotate(total=Sum('charged_amount'))}
            series = []
            day = first
            while day <= today:
                key = day.isoformat()
                series.append({'date': key, 'deposits': _money(deposit_rows.get(key)), 'spend': _money(spend_rows.get(key))})
                day += timedelta(days=1)
            return {
                'float_total': sum((c.balance for c in card_rows), Decimal('0.00')),
                'avg_balance': (sum((c.balance for c in card_rows), Decimal('0.00')) / len(card_rows)) if card_rows else Decimal('0.00'),
                'below_threshold': below,
                'at_floor': sum(1 for c in card_rows if c.balance <= Decimal(str(settings.RFID_BALANCE_FLOOR))),
                'near_strike_limit': sum(1 for c in card_rows if c.insufficient_meal_count >= settings.STRIKE_LIMIT - 2),
                'deposits_vs_spend': series,
            }
        return _cached(request, 'wallet-health', {}, build)


@extend_schema(tags=['analytics'], parameters=[OpenApiParameter('from', OpenApiTypes.DATE), OpenApiParameter('to', OpenApiTypes.DATE)], responses=OpenApiTypes.OBJECT)
class OperatorsAnalyticsView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('ANALYTICS')]

    def get(self, request):
        start, end, error = _date_range(request)
        if error:
            return error
        filters = {'from': start.isoformat(), 'to': end.isoformat()}

        def build():
            operators = CustomUser.objects.filter(role='operator').order_by('last_name', 'first_name')
            school = get_admin_scope(request.user)
            if school is not None:
                operators = operators.filter(school=school)
            output = []
            for operator in operators:
                sessions = ScanSession.objects.filter(operator=operator, start_at__date__gte=start, start_at__date__lte=end)
                session_ids = sessions.values('id')
                txns = Transaction.objects.filter(
                    session_id__in=session_ids, transaction_date__date__gte=start, transaction_date__date__lte=end,
                    transaction_status='successful', is_voided=False,
                )
                totals = txns.aggregate(revenue=Sum('charged_amount'))
                variance = Reconciliation.objects.filter(session_id__in=session_ids).aggregate(total=Sum('variance'))['total']
                reversals = Reversal.objects.filter(
                    transaction__session__operator=operator, reversed_at__date__gte=start, reversed_at__date__lte=end,
                ).count()
                scan_counts = ScannedData.objects.filter(session__operator=operator, scanned_at__date__gte=start, scanned_at__date__lte=end).aggregate(
                    total=Count('id'), nfc=Count('id', filter=Q(scan_source='nfc')),
                )
                total_scans, nfc_scans = scan_counts['total'] or 0, scan_counts['nfc'] or 0
                output.append({
                    'operator_id': str(operator.id),
                    'operator': f'{operator.first_name} {operator.last_name}'.strip() or operator.username,
                    'sessions': sessions.count(), 'revenue': _money(totals['revenue']),
                    'variance_total': _money(variance), 'reversals': reversals,
                    'nfc_scans': nfc_scans, 'total_scans': total_scans,
                    'nfc_share': round(nfc_scans / total_scans, 4) if total_scans else 0,
                })
            return {'operators': output}
        return _cached(request, 'operators', filters, build)


@extend_schema(tags=['analytics'], parameters=[OpenApiParameter('from', OpenApiTypes.DATE), OpenApiParameter('to', OpenApiTypes.DATE)], responses=OpenApiTypes.OBJECT)
class ClassesAnalyticsView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('ANALYTICS')]

    def get(self, request):
        start, end, error = _date_range(request)
        if error:
            return error
        filters = {'from': start.isoformat(), 'to': end.isoformat()}

        def build():
            rows = _transactions(start, end, request).values('student_or_staff__class_room').annotate(
                meals=Count('id'), spend=Sum('charged_amount'),
                penalties=Sum('charged_amount', filter=Q(transaction_status='penalty')),
            ).order_by('student_or_staff__class_room')
            return [{'class_room': r['student_or_staff__class_room'] or '', 'meals': r['meals'], 'spend': _money(r['spend']), 'penalties': _money(r['penalties'])} for r in rows]
        return _cached(request, 'classes', filters, build)


@extend_schema(tags=['analytics'], parameters=[OpenApiParameter('from', OpenApiTypes.DATE), OpenApiParameter('to', OpenApiTypes.DATE)], responses=OpenApiTypes.OBJECT)
class PenaltiesAnalyticsView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('ANALYTICS')]

    def get(self, request):
        start, end, error = _date_range(request)
        if error:
            return error
        qs = _transactions(start, end, request).filter(transaction_status='penalty')
        totals = qs.aggregate(count=Count('id'), amount=Sum('charged_amount'))
        near = RFIDCard.objects.filter(
            is_active=True, insufficient_meal_count__gte=settings.STRIKE_LIMIT - 2,
        ).select_related('student_or_staff')
        school = get_admin_scope(request.user)
        if school is not None:
            near = near.filter(student_or_staff__school=school)
        return Response({
            'count': totals['count'] or 0,
            'amount': _money(totals['amount']),
            'students_near_limit': [{
                'student_id': str(c.student_or_staff_id),
                'name': f'{c.student_or_staff.first_name} {c.student_or_staff.last_name}'.strip(),
                'class_room': c.student_or_staff.class_room,
                'insufficient_meal_count': c.insufficient_meal_count,
            } for c in near],
        })
