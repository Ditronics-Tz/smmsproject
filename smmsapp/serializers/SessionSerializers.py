from rest_framework import serializers
from ..models import ScanSession,ScannedData, RFIDCard, CanteenItem, Transaction

# ---- SESSION SERIALIZER -----
class ScanSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScanSession
        fields = ['id', 'operator', 'type', 'status', 'start_at', 'end_at', 'updated_at']
        read_only_fields = ['id', 'start_at', 'end_at', 'updated_at']


# ----- SCANNED DATA SERIALIZER ----
class ScannedDataSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    item_name = serializers.SerializerMethodField()
    item_price = serializers.SerializerMethodField()

    class Meta:
        model = ScannedData
        fields = ['id', 'session', 'student', 'student_name', 'rfid_card', 'item_name', 'item_price', 'scanned_at']
        read_only_fields = ['id', 'scanned_at']

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"

    def get_item_name(self, obj):
        return obj.canteenitem.name if hasattr(obj, 'canteenitem') else None

    def get_item_price(self, obj):
        return obj.canteenitem.price if hasattr(obj, 'canteenitem') else None
    

# ------ TRANSACTION SERIALIZER -----
class TransactionSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    item_name = serializers.SerializerMethodField()
    item_price = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = ['id', 'student_name', 'rfid_card', 'item_name', 'item_price', 'amount', 'transaction_date', 'transaction_status']

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"

    def get_item_name(self, obj):
        return obj.canteenitem.name if hasattr(obj, 'canteenitem') else None

    def get_item_price(self, obj):
        return obj.canteenitem.price if hasattr(obj, 'canteenitem') else None


