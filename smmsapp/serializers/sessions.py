from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from decimal import Decimal
from ..models import ScanSession,ScannedData, RFIDCard, CanteenItem, Transaction
from ..services.session_summary import session_summary
from .resources import TransactionSerializer as _TransactionSerializer

# ---- SESSION SERIALIZER -----
class ScanSessionSerializer(serializers.ModelSerializer):
    session_status = serializers.CharField(source='status', read_only=True)
    status = serializers.SerializerMethodField()
    scanned_value = serializers.SerializerMethodField()
    penalty_value = serializers.SerializerMethodField()
    expected_cash = serializers.SerializerMethodField()
    variance = serializers.SerializerMethodField()

    class Meta:
        model = ScanSession
        fields = ['id', 'operator', 'type', 'status', 'session_status', 'start_at', 'end_at',
                  'scanned_value', 'penalty_value', 'expected_cash', 'variance']
        read_only_fields = ['id', 'start_at', 'end_at']

    def _summary(self, obj):
        if not hasattr(obj, '_contract_summary'):
            obj._contract_summary = session_summary(obj)
        return obj._contract_summary

    def get_scanned_value(self, obj):
        return self._summary(obj)['scanned_value']

    def get_penalty_value(self, obj):
        return self._summary(obj)['penalty_value']

    def get_expected_cash(self, obj):
        return self._summary(obj)['expected_cash']

    def get_variance(self, obj):
        return self._summary(obj)['variance']

    def get_status(self, obj):
        return self._summary(obj)['status']


# ---- REQUEST BODIES FOR THE SESSION APIViews ----
class ScanRFIDRequestSerializer(serializers.Serializer):
    session_id = serializers.UUIDField(required=False, allow_null=True)
    card_number = serializers.CharField(required=False, allow_blank=True)
    card_uid = serializers.CharField(required=False, allow_blank=True)
    client_scan_id = serializers.UUIDField(required=False, allow_null=True)
    scan_source = serializers.ChoiceField(choices=['usb', 'nfc', 'manual'], required=False)
    item_id = serializers.UUIDField(required=False, allow_null=True)


class StartSessionRequestSerializer(serializers.Serializer):
    # Reuses the model constant so this shares one enum component with
    # ScanSession.type instead of declaring a second set with identical values.
    type = serializers.ChoiceField(
        choices=ScanSession.SESSION_TYPE_CHOICES, required=False, default='breakfast',
    )


class EndSessionRequestSerializer(serializers.Serializer):
    session_id = serializers.UUIDField(required=False, allow_null=True)
    expected_cash = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=Decimal('0.00'),
    )
    reason = serializers.CharField(required=False, allow_blank=True)


class SessionListRequestSerializer(serializers.Serializer):
    session_id = serializers.UUIDField(required=False, allow_null=True)
    search = serializers.CharField(required=False, allow_blank=True, default='')


class TransactionListRequestSerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, default='')


class ReconciliationSummarySerializer(serializers.Serializer):
    """Reconciliation is returned as strings because variance is Decimal."""
    id = serializers.UUIDField()
    scanned_value = serializers.CharField()
    expected_cash = serializers.CharField()
    variance = serializers.CharField()
    status = serializers.CharField()
    reason = serializers.CharField()


class EndSessionResponseSerializer(serializers.Serializer):
    scanned_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    penalty_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    expected_cash = serializers.DecimalField(max_digits=12, decimal_places=2)
    variance = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.CharField()


# ----- SCANNED DATA SERIALIZER ----
class ScannedDataSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_price = serializers.CharField(source="item.price", read_only=True)
    card_number = serializers.CharField(source="rfid_card.card_number", read_only=True)

    class Meta:
        model = ScannedData
        fields = ['id', 'session', 'student_name', 'card_number', 'item_name', 'item_price', 'scanned_at', 'scan_source']
        read_only_fields = ['id', 'scanned_at']

    def get_student_name(self, obj) -> str:
        return f"{obj.student_or_staff.first_name} {obj.student_or_staff.last_name}"
    

# ------ TRANSACTION SERIALIZER -----
# TransactionSerializer has a single definition in serializers.resources and is
# re-exported here. Two identical ModelSerializers for the same model produced
# two different components both named "Transaction", so the schema served one
# endpoint's shape to the other.
TransactionSerializer = _TransactionSerializer


