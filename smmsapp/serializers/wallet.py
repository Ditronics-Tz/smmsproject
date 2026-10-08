from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
import re
from ..models import (
    RFIDCard, BankDeposit, Transaction, LedgerEntry,
    ScanSession, Reconciliation, Reversal, CustomUser,
)


class BankDepositSerializer(serializers.ModelSerializer):
    # BankDeposit's FK to RFIDCard is named `control_number` (to_field on
    # RFIDCard.control_number), so the card is reached through that attribute.
    student_name = serializers.CharField(
        source='control_number.student_or_staff.first_name', read_only=True
    )
    card_number = serializers.CharField(source='control_number.card_number', read_only=True)
    submitted_by_name = serializers.CharField(
        source='submitted_by.get_full_name', read_only=True, allow_null=True
    )
    phone_masked = serializers.SerializerMethodField()

    def get_phone_masked(self, obj) -> str | None:
        phone = obj.submitted_by.mobile_number if obj.submitted_by_id else None
        if not phone:
            return None
        digits = re.sub(r'\D', '', phone)
        if digits.startswith('0') and len(digits) == 10:
            digits = '255' + digits[1:]
        if len(digits) < 6:
            return '***'
        return f"+{digits[:3]} {digits[3:4]}** *** {digits[-3:]}"

    class Meta:
        model = BankDeposit
        fields = [
            'id', 'control_number', 'card_number', 'student_name', 'amount',
            'status', 'processed_at', 'submitted_by', 'submitted_by_name',
            'payment_method', 'provider', 'reference', 'phone_masked', 'created_at',
        ]
        read_only_fields = ['id', 'control_number', 'created_at', 'processed_at']


class ProcessDepositSerializer(serializers.Serializer):
    deposit_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=[('process', 'Process'), ('fail', 'Fail')])
    reason = serializers.CharField(required=False, allow_blank=True)


class CreateDepositSerializer(serializers.Serializer):
    card_number = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    payment_method = serializers.ChoiceField(choices=['cash', 'mobile_money'], default='cash')
    provider = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    reference = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate(self, attrs):
        method = attrs['payment_method']
        provider = attrs.get('provider')
        if method == 'cash' and provider:
            raise serializers.ValidationError({'provider': 'Provider must be null for cash deposits.'})
        if method == 'mobile_money' and not provider:
            raise serializers.ValidationError({'provider': 'Provider is required for mobile money deposits.'})
        attrs['provider'] = provider or None
        return attrs


class LedgerEntrySerializer(serializers.ModelSerializer):
    card_number = serializers.CharField(source='rfid_card.card_number', read_only=True)
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    rfid_card_id = serializers.CharField(source='rfid_card.id', read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            'id', 'card_number', 'event_type', 'event_type_display',
            'amount', 'balance_before', 'balance_after',
            'ref_transaction', 'ref_deposit', 'rfid_card_id', 'timestamp',
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


class CardLedgerPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class CardLedgerViewSerializer(serializers.Serializer):
    """Output for a single ledger entry with running balance reconstruction."""
    timestamp = serializers.DateTimeField()
    event_type = serializers.CharField()
    event_type_display = serializers.CharField(source='get_event_type_display')
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    balance_before = serializers.DecimalField(max_digits=10, decimal_places=2)
    balance_after = serializers.DecimalField(max_digits=10, decimal_places=2)
    description = serializers.SerializerMethodField()

    def get_description(self, obj) -> str:
        return str(obj)
