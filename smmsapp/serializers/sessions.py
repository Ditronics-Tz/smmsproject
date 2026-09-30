from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from decimal import Decimal
from ..models import ScanSession,ScannedData, RFIDCard, CanteenItem, Transaction
from .resources import TransactionSerializer as _TransactionSerializer

# ---- SESSION SERIALIZER -----
class ScanSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScanSession
        fields = ['id', 'operator', 'type', 'status', 'start_at', 'end_at']
        read_only_fields = ['id', 'start_at', 'end_at']


# ---- REQUEST BODIES FOR THE SESSION APIViews ----
class ScanRFIDRequestSerializer(serializers.Serializer):
    session_id = serializers.UUIDField(required=False, allow_null=True)
    card_number = serializers.CharField(required=False, allow_blank=True)
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
    session = ScanSessionSerializer()
    reconciliation = ReconciliationSummarySerializer()


# ----- SCANNED DATA SERIALIZER ----
class ScannedDataSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_price = serializers.CharField(source="item.price", read_only=True)
    card_number = serializers.CharField(source="rfid_card.card_number", read_only=True)

    class Meta:
        model = ScannedData
        fields = ['id', 'session', 'student_name', 'card_number', 'item_name', 'item_price', 'scanned_at']
        read_only_fields = ['id', 'scanned_at']

    def get_student_name(self, obj) -> str:
        return f"{obj.student_or_staff.first_name} {obj.student_or_staff.last_name}"
    

# ------ TRANSACTION SERIALIZER -----
# TransactionSerializer has a single definition in serializers.resources and is
# re-exported here. Two identical ModelSerializers for the same model produced
# two different components both named "Transaction", so the schema served one
# endpoint's shape to the other.
TransactionSerializer = _TransactionSerializer


