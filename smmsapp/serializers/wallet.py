from rest_framework import serializers
from ..models import (
    RFIDCard, BankDeposit, Transaction, LedgerEntry,
    ScanSession, Reconciliation, Reversal, CustomUser,
)


class BankDepositSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(
        source='rfid_card.student_or_staff.first_name', read_only=True
    )
    card_number = serializers.CharField(source='rfid_card.card_number', read_only=True)
    submitted_by_name = serializers.CharField(
        source='submitted_by.get_full_name', read_only=True, allow_null=True
    )

    class Meta:
        model = BankDeposit
        fields = [
            'id', 'control_number', 'card_number', 'amount',
            'status', 'processed_at', 'submitted_by', 'submitted_by_name',
            'created_at',
        ]
        read_only_fields = ['id', 'control_number', 'created_at', 'processed_at']


class ProcessDepositSerializer(serializers.Serializer):
    deposit_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=[('process', 'Process'), ('fail', 'Fail')])
    reason = serializers.CharField(required=False, allow_blank=True)


class LedgerEntrySerializer(serializers.ModelSerializer):
    card_number = serializers.CharField(source='rfid_card.card_number', read_only=True)
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    rfid_card_id = serializers.CharField(source='rfid_card.id', read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            'id', 'card_number', 'event_type', 'event_type_display',
            'amount', 'balance_before', 'balance_after',
            'ref_transaction', 'ref_deposit', 'timestamp',
        ]
        read_only_fields = ['id', 'timestamp']


class ReconciliationSerializer(serializers.ModelSerializer):
    session_type = serializers.CharField(source='session.type', read_only=True)
    session_status = serializers.CharField(source='session.status', read_only=True)

    class Meta:
        model = Reconciliation
        fields = [
            'id', 'session', 'session_type', 'session_status',
            'scanned_value', 'expected_cash', 'variance',
            'status', 'reason', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'scanned_value', 'variance']


class ReversalSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField()
    reason = serializers.CharField()
    reversed_by_id = serializers.UUIDField(required=False, allow_null=True)


class CardLedgerPagination(serializers.PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class CardLedgerViewSerializer(serializers.Serializer):
    """Output for a single ledger entry with running balance reconstruction."""
    timestamp = serializers.DateTimeField()
    event_type = serializers.CharField()
    event_type_display = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    balance_before = serializers.DecimalField(max_digits=10, decimal_places=2)
    balance_after = serializers.DecimalField(max_digits=10, decimal_places=2)
    description = serializers.CharField(help_text='Human-readable description')