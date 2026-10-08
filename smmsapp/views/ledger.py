from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from smmsapp.models import (
    JournalEntry, JournalLine, LedgerAccount, LedgerIntegrityRun,
    ParentStudent, RFIDCard,
)
from smmsapp.permissions.features import FeatureEnabled
from smmsapp.permissions.roles import IsAdminOnly
from smmsapp.serializers.ledger import CardStatementLineSerializer, JournalEntrySerializer, TrialBalanceSerializer
from smmsapp.services.ledger import check_ledger_integrity
from smmsapp.utils import get_admin_scope


class LedgerPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100


def _date_filters(query_params, field):
    start_raw, end_raw = query_params.get('from'), query_params.get('to')
    start = parse_date(start_raw) if start_raw else None
    end = parse_date(end_raw) if end_raw else None
    if (start_raw and start is None) or (end_raw and end is None):
        return None, Response({'detail': 'Dates must use YYYY-MM-DD.', 'code': 'INVALID_DATE'}, status=status.HTTP_400_BAD_REQUEST)
    if start and end and start > end:
        return None, Response({'detail': '`from` must be on or before `to`.', 'code': 'INVALID_DATE_RANGE'}, status=status.HTTP_400_BAD_REQUEST)
    filters = {}
    if start:
        filters[f'{field}__date__gte'] = start
    if end:
        filters[f'{field}__date__lte'] = end
    return filters, None


class JournalListView(APIView, LedgerPagination):
    permission_classes = [IsAdminOnly, FeatureEnabled('LEDGER_UI')]

    @extend_schema(tags=['ledger'], responses=JournalEntrySerializer(many=True))
    def get(self, request):
        date_filters, error = _date_filters(request.query_params, 'created_at')
        if error:
            return error
        entries = JournalEntry.objects.prefetch_related('lines__account', 'lines__rfid_card').order_by('-created_at')
        entries = entries.filter(**date_filters)
        event_type = request.query_params.get('event_type')
        account = request.query_params.get('account')
        card_number = request.query_params.get('card_number')
        if event_type:
            entries = entries.filter(event_type=event_type)
        if account:
            entries = entries.filter(lines__account__code=account)
        if card_number:
            entries = entries.filter(lines__rfid_card__card_number=card_number)
        school = get_admin_scope(request.user)
        if school is not None:
            entries = entries.filter(lines__rfid_card__student_or_staff__school=school)
        entries = entries.distinct()
        page = self.paginate_queryset(entries, request, view=self)
        return self.get_paginated_response(JournalEntrySerializer(page, many=True).data)


class JournalDetailView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('LEDGER_UI')]

    @extend_schema(tags=['ledger'], responses=JournalEntrySerializer)
    def get(self, request, entry_id):
        entry = get_object_or_404(JournalEntry.objects.prefetch_related('lines__account', 'lines__rfid_card'), pk=entry_id)
        school = get_admin_scope(request.user)
        if school is not None and not entry.lines.filter(rfid_card__student_or_staff__school=school).exists():
            return Response({'detail': 'Entry not found.', 'code': 'NOT_FOUND'}, status=status.HTTP_404_NOT_FOUND)
        return Response(JournalEntrySerializer(entry).data)


class CardStatementView(APIView, LedgerPagination):
    permission_classes = [IsAuthenticated, FeatureEnabled('LEDGER_UI')]

    @extend_schema(tags=['ledger'], responses=CardStatementLineSerializer(many=True))
    def get(self, request, card_id):
        card = get_object_or_404(RFIDCard.objects.select_related('student_or_staff'), pk=card_id)
        user = request.user
        if user.role == 'admin':
            school = get_admin_scope(user)
            if school is not None and card.student_or_staff.school_id != school.id:
                return Response({'detail': 'Card not found.', 'code': 'NOT_FOUND'}, status=status.HTTP_404_NOT_FOUND)
        elif user.role == 'parent':
            if not ParentStudent.objects.filter(parent=user, student=card.student_or_staff).exists():
                return Response({'detail': 'Access denied.', 'code': 'FORBIDDEN'}, status=status.HTTP_403_FORBIDDEN)
        else:
            return Response({'detail': 'Access denied.', 'code': 'FORBIDDEN'}, status=status.HTTP_403_FORBIDDEN)
        date_filters, error = _date_filters(request.query_params, 'created_at')
        if error:
            return error
        lines = JournalLine.objects.filter(rfid_card=card).select_related('entry', 'account').filter(**date_filters).order_by('-created_at')
        page = self.paginate_queryset(lines, request, view=self)
        return self.get_paginated_response(CardStatementLineSerializer(page, many=True).data)


class AccountStatementView(APIView, LedgerPagination):
    permission_classes = [IsAdminOnly, FeatureEnabled('LEDGER_UI')]

    @extend_schema(tags=['ledger'], responses=CardStatementLineSerializer(many=True))
    def get(self, request, code):
        account = get_object_or_404(LedgerAccount, code=code)
        date_filters, error = _date_filters(request.query_params, 'created_at')
        if error:
            return error
        lines = JournalLine.objects.filter(account=account).select_related('entry', 'account', 'rfid_card').filter(**date_filters).order_by('-created_at')
        page = self.paginate_queryset(lines, request, view=self)
        return self.get_paginated_response(CardStatementLineSerializer(page, many=True).data)


class TrialBalanceView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('LEDGER_UI')]

    @extend_schema(tags=['ledger'], responses=TrialBalanceSerializer)
    def get(self, request):
        as_of_raw = request.query_params.get('as_of')
        as_of = parse_date(as_of_raw) if as_of_raw else None
        if as_of_raw and as_of is None:
            return Response({'detail': '`as_of` must use YYYY-MM-DD.', 'code': 'INVALID_DATE'}, status=status.HTTP_400_BAD_REQUEST)
        lines = JournalLine.objects.all()
        if as_of:
            lines = lines.filter(created_at__date__lte=as_of)
        rows = []
        for account in LedgerAccount.objects.order_by('code'):
            totals = lines.filter(account=account).aggregate(
                debit=Sum('amount', filter=Q(direction='debit')),
                credit=Sum('amount', filter=Q(direction='credit')),
            )
            debit = totals['debit'] or 0
            credit = totals['credit'] or 0
            rows.append({'account': account.code, 'name': account.name, 'debit': str(debit), 'credit': str(credit), 'net': str(credit - debit)})
        return Response({'as_of': as_of.isoformat() if as_of else None, 'accounts': rows})


class LedgerIntegrityView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('LEDGER_UI')]

    @extend_schema(tags=['ledger'], responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        if request.query_params.get('run', '').lower() == 'true':
            result = check_ledger_integrity(persist=True)
            return Response(result)
        run = LedgerIntegrityRun.objects.order_by('-checked_at').first()
        if run is None:
            return Response({'detail': 'No integrity run has been recorded.', 'code': 'NOT_FOUND'}, status=status.HTTP_404_NOT_FOUND)
        return Response(run.result)
