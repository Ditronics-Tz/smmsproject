from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from smmsapp.models import (
    BankDeposit, CustomUser, DailyStats, InsightFlag, RFIDCard, ScanSession,
    ScannedData, Transaction,
)
from smmsapp.permissions.features import FeatureEnabled
from smmsapp.permissions.roles import IsAdminOnly
from smmsapp.services.audit import log_action, snapshot
from smmsapp.utils import get_admin_scope


class ResolveInsightSerializer(serializers.Serializer):
    note = serializers.CharField(allow_blank=False)


def _school_flag_scope(request, qs):
    school = get_admin_scope(request.user)
    if school is None:
        return qs
    operator_ids = [str(value) for value in CustomUser.objects.filter(school=school).values_list('id', flat=True)]
    session_ids = [str(value) for value in ScanSession.objects.filter(operator__school=school).values_list('id', flat=True)]
    deposit_ids = [str(value) for value in BankDeposit.objects.filter(control_number__student_or_staff__school=school).values_list('id', flat=True)]
    return qs.filter(
        Q(scan_a__student_or_staff__school=school) |
        Q(reference_type='operator', reference_id__in=operator_ids) |
        Q(reference_type='session', reference_id__in=session_ids) |
        Q(reference_type='deposit', reference_id__in=deposit_ids)
    ).distinct()


@extend_schema(tags=['insights'], parameters=[OpenApiParameter('date', OpenApiTypes.DATE)], responses=OpenApiTypes.OBJECT)
class ForecastView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('INSIGHTS')]

    def get(self, request):
        try:
            target = date.fromisoformat(request.query_params.get('date', timezone.localdate().isoformat()))
        except ValueError:
            return Response({'date': ['Use YYYY-MM-DD.']}, status=400)
        output = []
        school = get_admin_scope(request.user)
        for meal_type, _ in ScanSession.SESSION_TYPE_CHOICES:
            sample_dates = [target - timedelta(days=7 * week) for week in range(1, 9)]
            if school is None:
                sample_counts = dict(DailyStats.objects.filter(date__in=sample_dates, meal_type=meal_type).values_list('date', 'meals'))
                samples = [sample_counts[sample_day] for sample_day in sample_dates if sample_day in sample_counts]
            else:
                sample_counts = {row['transaction_date__date']: row['total'] for row in Transaction.objects.filter(
                    transaction_date__date__in=sample_dates,
                    session__type=meal_type,
                    student_or_staff__school=school,
                    transaction_status__in=['successful', 'penalty'],
                    is_voided=False,
                ).values('transaction_date__date').annotate(total=Count('id'))}
                samples = [sample_counts.get(sample_day, 0) for sample_day in sample_dates]
            if len(samples) < 2:
                expected, weeks_used = None, 0
            else:
                expected = int((Decimal(sum(samples)) / len(samples)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                weeks_used = len(samples)
            output.append({'meal_type': meal_type, 'expected_meals': expected, 'weeks_used': weeks_used})
        return Response(output)


@extend_schema(tags=['insights'], responses=OpenApiTypes.OBJECT)
class AtRiskStudentsView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('INSIGHTS')]

    def get(self, request):
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        prior_start = week_start - timedelta(days=28)
        students = CustomUser.objects.filter(role='student', is_active=True).order_by('last_name', 'first_name')
        school = get_admin_scope(request.user)
        if school is not None:
            students = students.filter(school=school)
        rows = []
        for student in students.iterator():
            current_scans = ScannedData.objects.filter(student_or_staff=student, scanned_at__date__gte=week_start, scanned_at__date__lte=today).count()
            prior_scans = ScannedData.objects.filter(student_or_staff=student, scanned_at__date__gte=prior_start, scanned_at__date__lt=week_start).count()
            weekly_average = prior_scans / 4
            penalties = Transaction.objects.filter(
                student_or_staff=student, transaction_status='penalty', is_voided=False,
                transaction_date__date__gte=today - timedelta(days=13), transaction_date__date__lte=today,
            ).count()
            cards = list(RFIDCard.objects.filter(student_or_staff=student, is_active=True))
            strike_count = max((card.insufficient_meal_count for card in cards), default=0)
            reasons = []
            detail = {}
            if weekly_average > 0 and current_scans < weekly_average * 0.5:
                reasons.append('dropped_scans')
                detail['scans_this_week'] = current_scans
                detail['four_week_weekly_average'] = round(weekly_average, 2)
            if penalties >= 3:
                reasons.append('repeated_penalties')
                detail['penalties_14_days'] = penalties
            if strike_count >= settings.STRIKE_LIMIT - 2:
                reasons.append('near_strike_limit')
                detail['insufficient_meal_count'] = strike_count
            if reasons:
                rows.append({
                    'student_id': str(student.id),
                    'name': f'{student.first_name} {student.last_name}'.strip(),
                    'class_room': student.class_room,
                    'reasons': reasons,
                    'detail': detail,
                })
        return Response(rows)


@extend_schema(
    tags=['insights'], parameters=[OpenApiParameter('status', OpenApiTypes.STR, enum=['open', 'resolved'])],
    responses=OpenApiTypes.OBJECT,
)
class AnomaliesView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('INSIGHTS')]

    def get(self, request):
        state = request.query_params.get('status', 'open')
        if state not in ('open', 'resolved'):
            return Response({'status': ['Use open or resolved.']}, status=400)
        flags = _school_flag_scope(request, InsightFlag.objects.filter(status=state)).order_by('-created_at')
        return Response([{
            'id': str(flag.id), 'kind': flag.kind, 'reference_type': flag.reference_type,
            'reference_id': flag.reference_id, 'detail': flag.detail,
            'status': flag.status, 'created_at': flag.created_at,
        } for flag in flags])


@extend_schema(tags=['insights'], request=ResolveInsightSerializer, responses=OpenApiTypes.OBJECT)
class ResolveAnomalyView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('INSIGHTS')]

    def post(self, request, flag_id):
        serializer = ResolveInsightSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        flag = get_object_or_404(_school_flag_scope(request, InsightFlag.objects.all()), id=flag_id)
        if flag.status == 'resolved':
            return Response({'code': 'INSIGHT_ALREADY_RESOLVED', 'detail': 'This anomaly is already resolved.'}, status=409)
        before = snapshot(flag)
        flag.status = 'resolved'
        flag.resolved_by = request.user
        flag.resolved_at = timezone.now()
        flag.note = serializer.validated_data['note']
        flag.save(update_fields=['status', 'resolved_by', 'resolved_at', 'note'])
        log_action('update', obj=flag, before=before, after=snapshot(flag), actor=request.user, request=request)
        return Response({'id': str(flag.id), 'status': flag.status, 'note': flag.note, 'resolved_at': flag.resolved_at})


@extend_schema(tags=['insights'], parameters=[OpenApiParameter('days', OpenApiTypes.INT, default=30)], responses=OpenApiTypes.OBJECT)
class DormantCardsView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('INSIGHTS')]

    def get(self, request):
        try:
            days = int(request.query_params.get('days', 30))
            if days <= 0 or days > 365:
                raise ValueError
        except ValueError:
            return Response({'days': ['Use a value from 1 to 365.']}, status=400)
        cutoff = timezone.now() - timedelta(days=days)
        cards = RFIDCard.objects.filter(is_active=True).select_related('student_or_staff')
        school = get_admin_scope(request.user)
        if school is not None:
            cards = cards.filter(student_or_staff__school=school)
        rows = []
        for card in cards.iterator():
            last_scan = ScannedData.objects.filter(rfid_card=card).order_by('-scanned_at').values_list('scanned_at', flat=True).first()
            if last_scan is None or last_scan < cutoff:
                rows.append({
                    'card_id': str(card.id), 'card_number': card.card_number,
                    'student': f'{card.student_or_staff.first_name} {card.student_or_staff.last_name}'.strip(),
                    'last_scan': last_scan,
                })
        return Response(rows)
