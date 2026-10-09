import csv
import io
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from smmsapp.models import FundContribution, JournalLine, SponsorFund, SponsorshipAllocation, CustomUser, TransactionPayment
from smmsapp.permissions.features import FeatureEnabled
from smmsapp.permissions.roles import IsAdminOnly
from smmsapp.serializers.sponsorship import (
    AllocationSerializer, FundCloseSerializer, FundContributionSerializer, SponsorFundSerializer,
)
from smmsapp.services.audit import log_action, snapshot
from smmsapp.services.ledger import post_fund_contribution, post_fund_refund, post_fund_transfer


def _funds_with_balances():
    zero = Value(Decimal('0.00'), output_field=DecimalField(max_digits=14, decimal_places=2))
    return SponsorFund.objects.annotate(
        balance=Coalesce(
            Sum('journal_lines__amount', filter=Q(journal_lines__account__code='2200', journal_lines__direction='credit')),
            zero,
        ) - Coalesce(
            Sum('journal_lines__amount', filter=Q(journal_lines__account__code='2200', journal_lines__direction='debit')),
            zero,
        ),
        students_covered=Count('allocations__student_id', filter=Q(allocations__is_active=True), distinct=True),
    ).order_by('name')


@extend_schema(tags=['sponsorship'], responses=SponsorFundSerializer(many=True))
class SponsorFundsView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('SPONSORSHIP')]

    def get(self, request):
        return Response(SponsorFundSerializer(_funds_with_balances(), many=True).data)

    @extend_schema(request=SponsorFundSerializer, responses={201: SponsorFundSerializer})
    def post(self, request):
        serializer = SponsorFundSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        fund = serializer.save(created_by=request.user)
        log_action('create', obj=fund, after=snapshot(fund), actor=request.user, request=request)
        fund = _funds_with_balances().get(pk=fund.pk)
        return Response(SponsorFundSerializer(fund).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['sponsorship'], responses=SponsorFundSerializer)
class SponsorFundDetailView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('SPONSORSHIP')]

    def get(self, request, fund_id):
        fund = get_object_or_404(_funds_with_balances(), pk=fund_id)
        return Response(SponsorFundSerializer(fund).data)

    @extend_schema(request=SponsorFundSerializer, responses=SponsorFundSerializer)
    def put(self, request, fund_id):
        fund = get_object_or_404(SponsorFund, pk=fund_id)
        if fund.status == 'closed':
            return Response({'code': 'FUND_CLOSED', 'detail': 'A closed fund cannot be edited.'}, status=409)
        serializer = SponsorFundSerializer(fund, data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        before = snapshot(fund)
        fund = serializer.save()
        log_action('update', obj=fund, before=before, after=snapshot(fund), actor=request.user, request=request)
        fund = _funds_with_balances().get(pk=fund.pk)
        return Response(SponsorFundSerializer(fund).data)


@extend_schema(tags=['sponsorship'], request=FundContributionSerializer, responses={201: FundContributionSerializer})
class FundContributionView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('SPONSORSHIP')]

    def post(self, request, fund_id):
        serializer = FundContributionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        with transaction.atomic():
            fund = get_object_or_404(SponsorFund.objects.select_for_update(), pk=fund_id)
            if fund.status != 'active':
                return Response({'code': 'FUND_NOT_ACTIVE', 'detail': 'Contributions require an active fund.'}, status=409)
            contribution = serializer.save(fund=fund, recorded_by=request.user)
            before = {'balance': str(_fund_balance(fund))}
            post_fund_contribution(contribution, actor=request.user)
            after = {'balance': str(_fund_balance(fund))}
            log_action('create', obj=contribution, before=before, after={**snapshot(contribution), **after}, actor=request.user, request=request)
        return Response(FundContributionSerializer(contribution).data, status=status.HTTP_201_CREATED)


def _fund_balance(fund):
    totals = JournalLine.objects.filter(account__code='2200', fund=fund).aggregate(
        credits=Sum('amount', filter=Q(direction='credit')),
        debits=Sum('amount', filter=Q(direction='debit')),
    )
    return (totals['credits'] or Decimal('0.00')) - (totals['debits'] or Decimal('0.00'))


def _report_dates(request):
    from datetime import date, timedelta
    end_raw = request.query_params.get('to')
    start_raw = request.query_params.get('from')
    try:
        end = date.fromisoformat(end_raw) if end_raw else timezone.localdate()
        start = date.fromisoformat(start_raw) if start_raw else end - timedelta(days=29)
    except ValueError:
        return None, None, Response({'code': 'INVALID_DATE', 'detail': 'Use YYYY-MM-DD.'}, status=400)
    if start > end:
        return None, None, Response({'code': 'INVALID_DATE_RANGE'}, status=400)
    return start, end, None


def _fund_report_rows(fund, start, end):
    payments = TransactionPayment.objects.filter(
        fund=fund, transaction__is_voided=False,
        transaction__transaction_status__in=['successful', 'penalty'],
        transaction__transaction_date__date__gte=start,
        transaction__transaction_date__date__lte=end,
    ).select_related('transaction__student_or_staff', 'transaction__session')
    result = {}
    for payment in payments:
        txn = payment.transaction
        key = str(txn.student_or_staff_id)
        row = result.setdefault(key, {
            'student_id': key, 'student_name': f'{txn.student_or_staff.first_name} {txn.student_or_staff.last_name}'.strip(),
            'class_room': txn.student_or_staff.class_room or '', 'meals': 0, 'amount': Decimal('0.00'),
        })
        row['meals'] += 1
        row['amount'] += payment.amount
    return list(result.values())


class SponsorFundDashboardView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('SPONSORSHIP')]

    @extend_schema(tags=['sponsorship'], responses=OpenApiTypes.OBJECT)
    def get(self, request, fund_id):
        fund = get_object_or_404(SponsorFund, pk=fund_id)
        start, end, error = _report_dates(request)
        if error:
            return error
        payments = TransactionPayment.objects.filter(
            fund=fund, transaction__is_voided=False, transaction__transaction_status__in=['successful', 'penalty'],
            transaction__transaction_date__date__gte=start, transaction__transaction_date__date__lte=end,
        )
        spent = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        contributed = FundContribution.objects.filter(fund=fund, received_at__date__gte=start, received_at__date__lte=end).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        daily = list(payments.values('transaction__transaction_date__date').annotate(amount=Sum('amount')).order_by('transaction__transaction_date__date'))
        by_meal = list(payments.values('transaction__session__type').annotate(amount=Sum('amount')).order_by('transaction__session__type'))
        by_class = list(payments.values('transaction__student_or_staff__class_room').annotate(amount=Sum('amount')).order_by('transaction__student_or_staff__class_room'))
        students = payments.values('transaction__student_or_staff_id').distinct().count()
        from datetime import timedelta
        recent_start = timezone.localdate() - timedelta(days=13)
        recent = TransactionPayment.objects.filter(
            fund=fund, transaction__is_voided=False, transaction__transaction_status__in=['successful', 'penalty'],
            transaction__transaction_date__date__gte=recent_start,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        avg_daily = recent / Decimal('14')
        return Response({
            'fund_id': fund.pk, 'from': start, 'to': end, 'balance': _fund_balance(fund),
            'total_contributed': contributed, 'total_spent': spent, 'students_covered': students,
            'average_spend_per_student_per_day': (spent / Decimal(max(students, 1)) / Decimal(max((end-start).days+1, 1))) if spent else Decimal('0.00'),
            'spend_by_day': [{'date': row['transaction__transaction_date__date'], 'amount': row['amount']} for row in daily],
            'spend_by_meal_type': [{'meal_type': row['transaction__session__type'], 'amount': row['amount']} for row in by_meal],
            'spend_by_class': [{'class_room': row['transaction__student_or_staff__class_room'], 'amount': row['amount']} for row in by_class],
            'projected_days_remaining': (_fund_balance(fund) / avg_daily) if avg_daily else None,
        })


class SponsorFundReportView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('SPONSORSHIP')]

    @extend_schema(tags=['sponsorship'], responses=OpenApiTypes.OBJECT)
    def get(self, request, fund_id):
        fund = get_object_or_404(SponsorFund, pk=fund_id)
        start, end, error = _report_dates(request)
        if error:
            return error
        hide_names = request.query_params.get('hide_names', 'true').lower() != 'false'
        rows = _fund_report_rows(fund, start, end)
        rows.sort(key=lambda row: row['student_id'])
        for row in rows:
            student_name = row.pop('student_name')
            row['student'] = f"S-{int(row['student_id'].replace('-', ''), 16) % 10000000:07d}" if hide_names else student_name
            row.pop('student_id', None)
            row['amount'] = str(row['amount'])
        totals = {
            'meals': sum(row['meals'] for row in rows),
            'amount': str(sum((Decimal(row['amount']) for row in rows), Decimal('0.00'))),
            'students_covered': len(rows),
        }
        classes = {}
        for row in rows:
            bucket = classes.setdefault(row['class_room'], {'meals': 0, 'amount': Decimal('0.00'), 'students': 0})
            bucket['meals'] += row['meals']; bucket['amount'] += Decimal(row['amount']); bucket['students'] += 1
        data = {'fund': fund.name, 'from': start, 'to': end, 'totals': totals, 'students': rows,
                'by_class': [{'class_room': key, **{**value, 'amount': str(value['amount'])}} for key, value in classes.items()]}
        fmt = request.query_params.get('format', 'json').lower()
        if fmt == 'csv':
            from smmsapp.services.exporter import EXPORT_SYNC_MAX_ROWS
            if len(rows) > EXPORT_SYNC_MAX_ROWS or request.query_params.get('async', '').lower() == 'true':
                from uuid import uuid4
                from smmsapp.views.exports import _make_token
                from smmsapp.tasks import generate_export_task
                filename = f'sponsorship_fund_report-{uuid4().hex}.csv'
                filters = {
                    'fund_id': fund.pk, 'from_date': start.isoformat(), 'to_date': end.isoformat(),
                    'hide_names': hide_names,
                }
                token = _make_token('sponsorship_fund_report', filename, request.user.id)
                generate_export_task.delay(
                    entity='sponsorship_fund_report', filename=filename,
                    user_id=str(request.user.id), filters=filters,
                )
                return Response({
                    'code': 202, 'message': 'Report export accepted.', 'token': token,
                }, status=202)
            import csv
            from io import StringIO
            output = StringIO(); writer = csv.DictWriter(output, fieldnames=['student', 'class_room', 'meals', 'amount'])
            writer.writeheader(); writer.writerows(rows)
            response = HttpResponse(output.getvalue(), content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="fund-{fund.pk}-report.csv"'
            return response
        if fmt == 'pdf':
            try:
                from weasyprint import HTML
                from django.template.loader import render_to_string
                html = render_to_string('sponsorship_report.html', {
                    'app_name': getattr(settings, 'APP_NAME', 'SMMS'), 'fund_name': fund.name,
                    'from_date': start, 'to_date': end, 'totals': totals, 'students': rows,
                })
                response = HttpResponse(HTML(string=html).write_pdf(), content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="fund-{fund.pk}-report.pdf"'
                return response
            except Exception:
                return Response({'code': 'PDF_EXPORT_UNAVAILABLE'}, status=501)
        if fmt != 'json':
            return Response({'format': ['Use json, csv, or pdf.']}, status=400)
        return Response(data)


@extend_schema(tags=['sponsorship'], request=FundCloseSerializer, responses=SponsorFundSerializer)
class CloseSponsorFundView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('SPONSORSHIP')]

    def post(self, request, fund_id):
        serializer = FundCloseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        with transaction.atomic():
            if data['disposition'] == 'transfer':
                ids = sorted({fund_id, data['target_fund_id']})
                locked = {row.pk: row for row in SponsorFund.objects.select_for_update().filter(pk__in=ids).order_by('id')}
                fund = locked.get(fund_id)
                if fund is None:
                    return Response({'detail': 'Not found.'}, status=404)
            else:
                fund = get_object_or_404(SponsorFund.objects.select_for_update(), pk=fund_id)
            if fund.status == 'closed':
                return Response({'code': 'FUND_CLOSED', 'detail': 'This fund is already closed.'}, status=409)
            balance = _fund_balance(fund)
            if data['disposition'] == 'transfer':
                target = locked.get(data['target_fund_id'])
                if target is None:
                    return Response({'detail': 'Transfer target not found.'}, status=404)
                if target.pk == fund.pk:
                    return Response({'target_fund_id': ['Target must be a different fund.']}, status=400)
                if target.status != 'active':
                    return Response({'code': 'FUND_NOT_ACTIVE', 'detail': 'Transfer target must be active.'}, status=409)
                if balance > 0:
                    post_fund_transfer(
                        fund, target, balance, transfer_id=f'close:{fund.id}:{target.id}', actor=request.user,
                        memo=f"Fund close transfer: {data['reason']}",
                    )
            elif balance > 0:
                post_fund_refund(
                    fund, balance, refund_id=f'close:{fund.id}', actor=request.user,
                    memo=f"Fund close refund: {data['reason']}",
                )
            before = snapshot(fund)
            fund.status = 'closed'
            fund.save(update_fields=['status'])
            SponsorshipAllocation.objects.filter(fund=fund, is_active=True).update(is_active=False)
            log_action(
                'update', obj=fund, before=before,
                after={**snapshot(fund), 'disposition': data['disposition'], 'reason': data['reason']},
                actor=request.user, request=request,
            )
        return Response(SponsorFundSerializer(_funds_with_balances().get(pk=fund.pk)).data)


@extend_schema(tags=['sponsorship'], request=AllocationSerializer, responses={201: AllocationSerializer})
class SponsorshipAllocationCreateView(APIView, PageNumberPagination):
    permission_classes = [IsAdminOnly, FeatureEnabled('SPONSORSHIP')]
    page_size = 50

    def get(self, request):
        allocations = SponsorshipAllocation.objects.select_related('fund', 'student').order_by('priority', 'id')
        if request.query_params.get('fund'):
            allocations = allocations.filter(fund_id=request.query_params['fund'])
        if request.query_params.get('student'):
            allocations = allocations.filter(student_id=request.query_params['student'])
        rows = [{
            'id': row.id, 'fund_id': row.fund_id, 'fund_name': row.fund.name,
            'student_id': str(row.student_id),
            'student_name': f'{row.student.first_name} {row.student.last_name}'.strip(),
            'meal_types': row.meal_types, 'daily_cap': row.daily_cap, 'per_meal_cap': row.per_meal_cap,
            'valid_from': row.valid_from, 'valid_to': row.valid_to, 'priority': row.priority,
            'is_active': row.is_active,
        } for row in allocations]
        page = self.paginate_queryset(rows, request, view=self)
        return self.get_paginated_response(page)

    def post(self, request):
        serializer = AllocationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        fund = get_object_or_404(SponsorFund, pk=data['fund_id'])
        student = get_object_or_404(CustomUser, pk=data['student_id'], role='student')
        if fund.status != 'active':
            return Response({'code': 'FUND_NOT_ACTIVE', 'detail': 'Allocations require an active fund.'}, status=409)
        if data['valid_from'] < fund.start_date or (fund.end_date and data['valid_from'] > fund.end_date):
            return Response({'valid_from': ['Allocation must start within the fund validity period.']}, status=400)
        if fund.end_date and (data.get('valid_to') is None or data['valid_to'] > fund.end_date):
            return Response({'valid_to': ['Allocation must end no later than the fund end date.']}, status=400)
        if SponsorshipAllocation.objects.filter(fund=fund, student=student, is_active=True).exists():
            return Response({'code': 'ALLOCATION_OVERLAP', 'detail': 'This student already has an active allocation from this fund.'}, status=409)
        try:
            with transaction.atomic():
                allocation = serializer.save(fund=fund, student=student, is_active=True)
        except IntegrityError:
            return Response({'code': 'ALLOCATION_OVERLAP', 'detail': 'This student already has an active allocation from this fund.'}, status=409)
        log_action('create', obj=allocation, after={
            'fund_id': fund.id, 'student_id': student.id, 'meal_types': allocation.meal_types,
            'daily_cap': allocation.daily_cap, 'per_meal_cap': allocation.per_meal_cap,
            'valid_from': allocation.valid_from, 'valid_to': allocation.valid_to,
        }, actor=request.user, request=request)
        return Response(AllocationSerializer(allocation).data, status=status.HTTP_201_CREATED)


class SponsorshipAllocationBulkView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('SPONSORSHIP')]

    @extend_schema(tags=['sponsorship'], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        mode = request.data.get('mode')
        dry_run = request.data.get('dry_run', False)
        if not isinstance(dry_run, bool):
            return Response({'dry_run': ['Must be a boolean.']}, status=400)
        fund = get_object_or_404(SponsorFund, pk=request.data.get('fund_id'))
        if fund.status != 'active':
            return Response({'code': 'FUND_NOT_ACTIVE'}, status=409)
        defaults = {key: request.data[key] for key in (
            'meal_types', 'daily_cap', 'per_meal_cap', 'valid_from', 'valid_to', 'priority'
        ) if key in request.data}
        raw_rows = []
        if mode == 'student_ids':
            raw_rows = [{'student_id': sid, **defaults} for sid in request.data.get('student_ids', [])]
            if not raw_rows:
                return Response({'student_ids': ['Supply at least one student.']}, status=400)
        elif mode == 'class_room':
            students = CustomUser.objects.filter(role='student', is_active=True, class_room=request.data.get('class_room'))
            raw_rows = [{'student_id': str(student.pk), **defaults} for student in students]
        elif mode == 'csv':
            try:
                reader = csv.DictReader(io.StringIO(request.data.get('csv', '')))
                if not reader.fieldnames or 'registration_number' not in reader.fieldnames:
                    raise ValueError('CSV must include registration_number column.')
                for row in reader:
                    student = CustomUser.objects.filter(role='student', username=row.get('registration_number', '').strip()).first()
                    overrides = {}
                    for field in ('daily_cap', 'per_meal_cap', 'valid_from', 'valid_to', 'priority'):
                        if row.get(field, '').strip():
                            overrides[field] = row[field].strip()
                    if row.get('meal_types', '').strip():
                        overrides['meal_types'] = [part.strip() for part in row['meal_types'].split('|') if part.strip()]
                    raw_rows.append({'student_id': str(student.pk) if student else '', **defaults, **overrides})
            except (csv.Error, ValueError) as exc:
                return Response({'total': 0, 'valid': 0, 'errors': [{'row': 1, 'reason': str(exc)}], 'rows': []}, status=400)
        else:
            return Response({'mode': ['Use class_room, student_ids, or csv.']}, status=400)

        valid, errors, seen = [], [], set()
        for index, row in enumerate(raw_rows, start=2 if mode == 'csv' else 1):
            row = {**defaults, **row, 'fund_id': fund.pk}
            serializer = AllocationSerializer(data=row)
            if not serializer.is_valid():
                errors.append({'row': index, 'reason': serializer.errors})
                continue
            sid = str(serializer.validated_data['student_id'])
            if sid in seen:
                errors.append({'row': index, 'reason': 'Duplicate student in request.'})
                continue
            seen.add(sid)
            student = CustomUser.objects.filter(pk=sid, role='student', is_active=True).first()
            if student is None:
                errors.append({'row': index, 'reason': 'Student not found or inactive.'})
                continue
            data = serializer.validated_data
            if data['valid_from'] < fund.start_date or (fund.end_date and data['valid_from'] > fund.end_date):
                errors.append({'row': index, 'reason': 'Allocation dates are outside fund dates.'})
                continue
            if data.get('valid_to') and data['valid_to'] < data['valid_from']:
                errors.append({'row': index, 'reason': 'valid_to precedes valid_from.'})
                continue
            if fund.end_date and data.get('valid_to') and data['valid_to'] > fund.end_date:
                errors.append({'row': index, 'reason': 'valid_to exceeds fund end date.'})
                continue
            if SponsorshipAllocation.objects.filter(fund=fund, student=student, is_active=True).exists():
                errors.append({'row': index, 'reason': 'ALLOCATION_OVERLAP'})
                continue
            valid.append((index, student, data))
        rows = [{'row': index, 'student_id': str(student.pk), 'valid': True} for index, student, _ in valid]
        if not dry_run and errors:
            return Response({'total': len(raw_rows), 'valid': len(valid), 'errors': errors, 'rows': rows}, status=400)
        if not dry_run:
            try:
                with transaction.atomic():
                    for _, student, data in valid:
                        data.pop('fund_id', None)
                        data.pop('student_id', None)
                        allocation = SponsorshipAllocation.objects.create(
                            fund=fund, student=student, is_active=True, **data,
                        )
                        log_action('create', obj=allocation, after=snapshot(allocation), actor=request.user, request=request)
            except IntegrityError:
                return Response({'code': 'ALLOCATION_OVERLAP', 'detail': 'An allocation changed concurrently; no rows were saved.'}, status=409)
        return Response({'total': len(raw_rows), 'valid': len(valid), 'errors': errors, 'rows': rows})


@extend_schema(tags=['sponsorship'], responses=OpenApiTypes.OBJECT)
class SponsorshipAllocationDeactivateView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('SPONSORSHIP')]

    @extend_schema(tags=['sponsorship'], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request, allocation_id):
        allocation = get_object_or_404(SponsorshipAllocation, pk=allocation_id)
        if not allocation.is_active:
            return Response({'code': 'ALLOCATION_INACTIVE', 'detail': 'Allocation is already inactive.'}, status=409)
        before = snapshot(allocation)
        allocation.is_active = False
        allocation.save(update_fields=['is_active'])
        log_action('deactivate', obj=allocation, before=before, after=snapshot(allocation), actor=request.user, request=request)
        return Response({'id': allocation.id, 'is_active': False})
