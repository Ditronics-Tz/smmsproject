from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.conf import settings

from ..models import (
    RFIDCard, BankDeposit, Transaction, LedgerEntry,
    ScanSession, Reconciliation, Reversal, CustomUser,
)
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from ..serializers.system import CodeMessageSerializer
from ..serializers.resources import TransactionSerializer
from ..permissions.roles import IsAdminOnly, IsOperator, IsAdminOrOperator, IsAdminParentOrStaff, IsAdminOperatorOrParent
from ..permissions.features import FeatureEnabled
from ..services.audit import log_action, snapshot
from ..serializers.wallet import (
    CreateDepositSerializer,
    BankDepositSerializer, ProcessDepositSerializer, LedgerEntrySerializer,
    ReconciliationSerializer, ReversalSerializer, CardLedgerViewSerializer,
    CardLedgerPagination,
)


# ---------------------------
# Deposit (top-up) flow
# ---------------------------

@extend_schema(tags=['wallet'], request=CreateDepositSerializer,
    responses={201: BankDepositSerializer, 400: CodeMessageSerializer, 403: CodeMessageSerializer, 404: CodeMessageSerializer})
class CreateDepositView(APIView):
    """Parent submits a top-up deposit request for one of their children's cards."""
    permission_classes = [IsAdminParentOrStaff, FeatureEnabled('PAYMENTS')]

    def post(self, request):
        user = request.user
        serializer = CreateDepositSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'code': 400, 'message': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        card_number = data['card_number']

        # Validate the card exists and user has access (parent via ParentStudent, or staff)
        try:
            rfid_card = RFIDCard.objects.get(card_number=card_number, is_active=True)
        except RFIDCard.DoesNotExist:
            return Response(
                {'code': 404, 'message': 'Invalid or inactive RFID card'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check parent/staff access: parent must be linked via ParentStudent, or user is staff
        if user.role != 'staff':
            # parent must have a ParentStudent relationship with the card's owner (student)
            from ..models import ParentStudent
            has_access = ParentStudent.objects.filter(
                parent=user, student=rfid_card.student_or_staff
            ).exists()
            if not has_access:
                return Response(
                    {'code': 403, 'message': 'You do not have access to this card'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Create the pending deposit
        deposit = BankDeposit.objects.create(
            control_number=rfid_card.control_number,
            amount=data['amount'],
            payment_method=data['payment_method'],
            provider=data['provider'],
            reference=data.get('reference') or None,
            status='pending',
            submitted_by=user if user.role in ('parent', 'staff') else None,
        )

        # Notify admins/operators that a deposit needs processing
        from ..models import Notification
        admin_users = CustomUser.objects.filter(role='admin')
        for admin in admin_users:
            Notification.objects.create(
                title='New Deposit Request',
                recipient=admin,
                message=f"Deposit of {deposit.amount} for card {rfid_card.card_number} awaiting approval",
                type='transaction',
                status='pending',
            )

        try:
            log_action('create', obj=deposit, after=snapshot(deposit))
        except Exception:
            pass
        serializer = BankDepositSerializer(deposit)
        return Response({
            'code': 201,
            'message': 'Deposit request submitted, awaiting admin approval',
            'deposit': serializer.data,
        }, status=status.HTTP_201_CREATED)


@extend_schema(parameters=[
    OpenApiParameter('payment_method', OpenApiTypes.STR, enum=['cash', 'mobile_money']),
    OpenApiParameter('provider', OpenApiTypes.STR),
    OpenApiParameter('status', OpenApiTypes.STR, enum=['pending', 'processed', 'failed']),
    OpenApiParameter('from', OpenApiTypes.DATE, description='Inclusive start date.'),
    OpenApiParameter('to', OpenApiTypes.DATE, description='Inclusive end date.'),
])
class DepositListView(generics.ListAPIView):
    """List deposits: parent sees own; admin/operator sees all."""
    serializer_class = BankDepositSerializer
    pagination_class = CardLedgerPagination
    permission_classes = [IsAdminOperatorOrParent, FeatureEnabled('PAYMENTS')]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['payment_method', 'provider', 'status']

    def get_queryset(self):
        from django.utils.dateparse import parse_date
        if getattr(self, 'swagger_fake_view', False):
            return BankDeposit.objects.none()
        user = self.request.user
        if user.role == 'admin' or user.role == 'operator':
            queryset = BankDeposit.objects.all()
        else:
            # Parent: only their own deposits (those where submitted_by = user)
            queryset = BankDeposit.objects.filter(submitted_by=user)
        date_from = parse_date(self.request.query_params.get('from', ''))
        date_to = parse_date(self.request.query_params.get('to', ''))
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset.order_by('-created_at')


@extend_schema(tags=['wallet'], request=ProcessDepositSerializer,
    responses={200: BankDepositSerializer, 400: CodeMessageSerializer, 403: CodeMessageSerializer, 404: CodeMessageSerializer})
class ProcessDepositView(APIView):
    """Admin/operator approves or fails a pending deposit.
    On approval: credits RFIDCard.balance atomically (select_for_update),
    writes LedgerEntry(event_type='deposit'), sets processed_at, notifies parent.
    """
    permission_classes = [IsAdminOrOperator, FeatureEnabled('PAYMENTS')]

    def post(self, request):
        serializer = ProcessDepositSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        deposit_id = serializer.validated_data['deposit_id']
        action = serializer.validated_data['action']
        reason = serializer.validated_data.get('reason', '')

        deposit = get_object_or_404(BankDeposit, id=deposit_id)

        # Idempotency guard: if already processed or failed, just return current state
        if deposit.status != 'pending':
            return Response({
                'code': 409,
                'message': f'Deposit already {deposit.status}; no action taken',
            }, status=status.HTTP_409_CONFLICT)

        if action == 'process':
            # Credit the card balance atomically with row lock
            with transaction.atomic():
                deposit = BankDeposit.objects.select_for_update().get(pk=deposit.pk)
                if deposit.status != 'pending':
                    return Response({
                        'code': 409,
                        'message': f'Deposit already {deposit.status}; no action taken',
                    }, status=status.HTTP_409_CONFLICT)
                rfid_card = RFIDCard.objects.select_for_update().get(
                    control_number=deposit.control_number
                )
                old_balance = rfid_card.balance
                rfid_card.balance += deposit.amount
                if settings.STRIKE_RESET_ON_DEPOSIT:
                    rfid_card.insufficient_meal_count = 0
                rfid_card.save()

                # Write ledger entry for the deposit
                LedgerEntry.objects.create(
                    rfid_card=rfid_card,
                    event_type='deposit',
                    amount=deposit.amount,
                    balance_before=old_balance,
                    balance_after=rfid_card.balance,
                    ref_deposit=deposit,
                )
                from ..services.ledger import post_deposit
                post_deposit(deposit, actor=request.user)
                deposit.status = 'processed'
                deposit.processed_at = timezone.now()
                deposit.save(update_fields=['status', 'processed_at'])

            try:
                log_action('approve', obj=deposit, after=snapshot(deposit))
            except Exception:
                pass

            # Notify the parent that their deposit was processed
            from ..models import CustomUser, Notification
            if deposit.submitted_by:
                Notification.objects.create(
                    title='Deposit Processed',
                    recipient=deposit.submitted_by,
                    message=f'Your deposit of {deposit.amount} for card {deposit.control_number} has been processed. '
                            f'Your new balance is {rfid_card.balance}.',
                    type='transaction',
                    status='sent',
                )

            from ..services.webhooks import dispatch_webhook_event
            transaction.on_commit(lambda: dispatch_webhook_event(
                rfid_card.student_or_staff.school_id, 'deposit.processed',
                {'deposit_id': str(deposit.id), 'card_id': str(rfid_card.id), 'amount': str(deposit.amount),
                 'payment_method': deposit.payment_method, 'reference': deposit.reference},
            ))

            return Response({
                'code': 200,
                'message': 'Deposit processed successfully',
                'deposit': BankDepositSerializer(deposit).data,
                'ledger': LedgerEntrySerializer(
                    LedgerEntry.objects.filter(rfid_card=rfid_card, event_type='deposit').order_by('-timestamp').first(),
                ).data,
            }, status=status.HTTP_200_OK)

        elif action == 'fail':
            deposit.status = 'failed'
            deposit.save()

            # Notify the parent
            if deposit.submitted_by:
                Notification.objects.create(
                    title='Deposit Failed',
                    recipient=deposit.submitted_by,
                    message=f'Your deposit of {deposit.amount} for card {deposit.control_number} failed.',
                    type='transaction',
                    status='failed',
                )

            return Response({
                'code': 200,
                'message': 'Deposit marked as failed',
            }, status=status.HTTP_200_OK)


# ---------------------------
# Ledger (chronological per-card audit trail)
# ---------------------------

class CardLedgerPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class CardLedgerView(generics.ListAPIView):
    """Admin/parent sees paginated LedgerEntry rows for a given card.
    Reconstructs the running balance entry-by-entry.
    """
    serializer_class = CardLedgerViewSerializer
    pagination_class = CardLedgerPagination
    permission_classes = [IsAdminOrOperator, FeatureEnabled('LEDGER_UI')]

    def get_queryset(self):
        card_identifier = self.request.query_params.get('card_number') or self.request.data.get('card_number')
        if not card_identifier:
            return LedgerEntry.objects.none()
        return LedgerEntry.objects.filter(
            rfid_card__card_number=card_identifier
        ).order_by('timestamp')


# ---------------------------
# Transaction reversal (void)
# ---------------------------

@extend_schema(tags=['wallet'], request=ReversalSerializer,
    responses={200: TransactionSerializer, 400: CodeMessageSerializer, 403: CodeMessageSerializer, 404: CodeMessageSerializer, 409: CodeMessageSerializer})
class ReverseTransactionView(APIView):
    """Admin/operator voids a transaction, restoring the exact amount to the card balance.
    Idempotent: cannot be applied twice (transaction.is_voided guard + unique Reversal row).
    """
    permission_classes = [IsAdminOrOperator, FeatureEnabled('PAYMENTS')]

    def post(self, request):
        serializer = ReversalSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        transaction_id = serializer.validated_data['transaction_id']
        reason = serializer.validated_data['reason']
        reversed_by_id = serializer.validated_data.get('reversed_by_id')

        txn = get_object_or_404(Transaction, id=transaction_id)

        # Idempotency guard 1: already voided?
        if txn.is_voided:
            return Response({
                'code': 409,
                'message': 'This transaction has already been voided',
            }, status=status.HTTP_409_CONFLICT)

        # Idempotency guard 2: already has a Reversal row?
        if Reversal.objects.filter(transaction=txn).exists():
            return Response({
                'code': 409,
                'message': 'A reversal record already exists for this transaction',
            }, status=status.HTTP_409_CONFLICT)

        with transaction.atomic():
            # Lock the card row so concurrent deposits/scans can't interfere
            rfid_card = RFIDCard.objects.select_for_update().get(
                control_number=txn.rfid_card.control_number
            )

            old_balance = rfid_card.balance
            # Restore the exact amount that was deducted (includes penalty if applicable)
            restore_amount = txn.preorder_item.unit_price if txn.preorder_item_id else txn.charged_amount
            rfid_card.balance += restore_amount
            if txn.transaction_status == 'penalty':
                rfid_card.insufficient_meal_count = max(0, rfid_card.insufficient_meal_count - 1)
            rfid_card.save()

            # Write ledger entry for the reversal
            LedgerEntry.objects.create(
                rfid_card=rfid_card,
                event_type='reversal',
                amount=restore_amount,  # positive: restores the actual deduction
                balance_before=old_balance,
                balance_after=rfid_card.balance,
                ref_transaction=txn,
            )

            # Mark the transaction as voided
            txn.is_voided = True
            txn.save()

            from ..services.stock import restore_stock
            restore_stock(txn.item, transaction_record=txn, actor=request.user, reason=f'Reversal {txn.id}')

            # Create the Reversal record (unique constraint => cannot be applied twice)
            try:
                log_action('reverse', obj=txn, after=snapshot(txn))
            except Exception:
                pass
            Reversal.objects.create(
                transaction=txn,
                reversed_by_id=reversed_by_id,
                reason=reason,
            )
            reversal = Reversal.objects.get(transaction=txn)
            if txn.preorder_item_id:
                preorder = txn.preorder_item.preorder
                from ..services.preorders import release_preorder
                if preorder.status == 'placed':
                    release_preorder(preorder, actor=request.user)
                preorder.status = 'cancelled'
                preorder.cancelled_at = timezone.now()
                preorder.note = 'Cancelled after reversal of a fulfilled pre-order transaction.'
                preorder.save(update_fields=['status', 'cancelled_at', 'note'])
            original_journals = txn.journal_entries.all()
            if original_journals.exists():
                from ..services.ledger import post_reversal
                for original_journal in original_journals.order_by('created_at', 'id'):
                    post_reversal(original_journal, reversal, actor=request.user)
            elif restore_amount > 0:
                # Transactions created before double-entry journal rollout do
                # not have a source entry to mirror; preserve balanced accounts
                # using the stored actual charge rather than the assessed price.
                from ..services.ledger import post_entry
                income_account = '4100' if txn.transaction_status == 'penalty' else '4000'
                post_entry('reversal', [
                    {'account': '2000', 'rfid_card': rfid_card, 'direction': 'credit', 'amount': restore_amount},
                    {'account': income_account, 'direction': 'debit', 'amount': restore_amount},
                ], f'reversal:{txn.id}', refs={'ref_reversal': reversal}, actor=request.user, memo=reason)

            # Notify the relevant parties
            from ..models import Notification, CustomUser
            # Notify the card's student/Staff parent
            student_or_staff = txn.student_or_staff
            # Find parents of this student
            from ..models import ParentStudent
            parents = ParentStudent.objects.filter(student=student_or_staff)
            for parent_entry in parents:
                Notification.objects.create(
                    title='Transaction Voided',
                    recipient=parent_entry.parent,
                    message=f'Transaction for {student_or_staff.username} ({txn.item.name}) has been voided. '
                            f'Balance restored to {rfid_card.balance}.',
                    type='transaction',
                    status='sent',
                )

            return Response({
                'code': 200,
                'message': 'Transaction reversed successfully, balance restored',
                'transaction': {
                    'id': str(txn.id),
                    'item': txn.item.name,
                    'amount': str(restore_amount),
                    'new_balance': str(rfid_card.balance),
                },
                'ledger': LedgerEntrySerializer(
                    LedgerEntry.objects.filter(rfid_card=rfid_card, event_type='reversal').order_by('-timestamp').first(),
                ).data,
            }, status=status.HTTP_200_OK)
