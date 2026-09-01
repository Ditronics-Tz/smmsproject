from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from ..models import (
    RFIDCard, BankDeposit, Transaction, LedgerEntry,
    ScanSession, Reconciliation, Reversal, CustomUser,
)
from ..models.sessions import ScanSession as ScanSessionModel
from ..permissions.roles import IsAdminOnly, IsOperator, IsAdminOrOperator, IsAdminOrParent
from ..serializers.wallet import (
    BankDepositSerializer, ProcessDepositSerializer, LedgerEntrySerializer,
    ReconciliationSerializer, ReversalSerializer, CardLedgerViewSerializer,
    CardLedgerPagination,
)


# ---------------------------
# Deposit (top-up) flow
# ---------------------------

class CreateDepositView(APIView):
    """Parent submits a top-up deposit request for one of their children's cards."""
    permission_classes = [IsAdminOrParent]

    def post(self, request):
        user = request.user
        card_number = request.data.get('card_number')
        amount = request.data.get('amount')

        if not card_number or not amount:
            return Response(
                {'code': 400, 'message': 'card_number and amount are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
            amount=Decimal(amount),
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

        serializer = BankDepositSerializer(deposit)
        return Response({
            'code': 201,
            'message': 'Deposit request submitted, awaiting admin approval',
            'deposit': serializer.data,
        }, status=status.HTTP_201_CREATED)


class DepositListView(generics.ListAPIView):
    """List deposits: parent sees own; admin/operator sees all."""
    serializer_class = BankDepositSerializer
    pagination_class = CardLedgerPagination
    permission_classes = [IsAdminOrOperator]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin' or user.role == 'operator':
            return BankDeposit.objects.all().order_by('-created_at')
        # parent: only their own deposits (those where submitted_by = user)
        return BankDeposit.objects.filter(submitted_by=user).order_by('-created_at')


class ProcessDepositView(APIView):
    """Admin/operator approves or fails a pending deposit.
    On approval: credits RFIDCard.balance atomically (select_for_update),
    writes LedgerEntry(event_type='deposit'), sets processed_at, notifies parent.
    """
    permission_classes = [IsAdminOrOperator]

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
                rfid_card = RFIDCard.objects.select_for_update().get(
                    control_number=deposit.control_number
                )
                old_balance = rfid_card.balance
                rfid_card.balance += deposit.amount
                rfid_card.save()

                # Write ledger entry for the deposit
                from ..serializers.wallet import LedgerEntrySerializer
                LedgerEntry.objects.create(
                    rfid_card=rfid_card,
                    event_type='deposit',
                    amount=deposit.amount,
                    balance_before=old_balance,
                    balance_after=rfid_card.balance,
                    ref_deposit=deposit,
                )

            deposit.status = 'processed'
            deposit.processed_at = timezone.now()
            deposit.save()

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
    permission_classes = [IsAdminOrOperator]

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

class ReverseTransactionView(APIView):
    """Admin/operator voids a transaction, restoring the exact amount to the card balance.
    Idempotent: cannot be applied twice (transaction.is_voided guard + unique Reversal row).
    """
    permission_classes = [IsAdminOrOperator]

    def post(self, request):
        serializer = ReversalSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        transaction_id = serializer.validated_data['transaction_id']
        reason = serializer.validated_data['reason']
        reversed_by_id = serializer.validated_data.get('reversed_by_id')

        transaction = get_object_or_404(Transaction, id=transaction_id)

        # Idempotency guard 1: already voided?
        if transaction.is_voided:
            return Response({
                'code': 409,
                'message': 'This transaction has already been voided',
            }, status=status.HTTP_409_CONFLICT)

        # Idempotency guard 2: already has a Reversal row?
        if Reversal.objects.filter(transaction=transaction).exists():
            return Response({
                'code': 409,
                'message': 'A reversal record already exists for this transaction',
            }, status=status.HTTP_409_CONFLICT)

        with transaction.atomic():
            # Lock the card row so concurrent deposits/scans can't interfere
            rfid_card = RFIDCard.objects.select_for_update().get(
                control_number=transaction.rfid_card.control_number
            )

            old_balance = rfid_card.balance
            # Restore the exact amount that was deducted (includes penalty if applicable)
            rfid_card.balance += transaction.amount
            rfid_card.save()

            # Write ledger entry for the reversal
            LedgerEntry.objects.create(
                rfid_card=rfid_card,
                event_type='reversal',
                amount=transaction.amount,  # positive: restores the deduction
                balance_before=old_balance,
                balance_after=rfid_card.balance,
                ref_transaction=transaction,
            )

            # Mark the transaction as voided
            transaction.is_voided = True
            transaction.save()

            # Create the Reversal record (unique constraint => cannot be applied twice)
            Reversal.objects.create(
                transaction=transaction,
                reversed_by_id=reversed_by_id,
                reason=reason,
            )

            # Notify the relevant parties
            from ..models import Notification, CustomUser
            # Notify the card's student/Staff parent
            student_or_staff = transaction.student_or_staff
            # Find parents of this student
            from ..models import ParentStudent
            parents = ParentStudent.objects.filter(student=student_or_staff)
            for parent_entry in parents:
                Notification.objects.create(
                    title='Transaction Voided',
                    recipient=parent_entry.parent,
                    message=f'Transaction for {student_or_staff.username} ({transaction.item.name}) has been voided. '
                            f'Balance restored to {rfid_card.balance}.',
                    type='transaction',
                    status='sent',
                )

            return Response({
                'code': 200,
                'message': 'Transaction reversed successfully, balance restored',
                'transaction': {
                    'id': str(transaction.id),
                    'item': transaction.item.name,
                    'amount': str(transaction.amount),
                    'new_balance': str(rfid_card.balance),
                },
                'ledger': LedgerEntrySerializer(
                    LedgerEntry.objects.filter(rfid_card=rfid_card, event_type='reversal').order_by('-timestamp').first(),
                ).data,
            }, status=status.HTTP_200_OK)