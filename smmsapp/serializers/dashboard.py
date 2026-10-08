from rest_framework import serializers
from datetime import date

# ---- COUNTS SERIALIZER -----
class CountsSerializer(serializers.Serializer):
    total_students = serializers.IntegerField()
    total_parents = serializers.IntegerField()
    total_staffs = serializers.IntegerField()
    total_available_balance = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_transactions = serializers.IntegerField()
    sessions = serializers.IntegerField()
    price_week = serializers.IntegerField()
    price_today = serializers.IntegerField()

# ---- SALES SUMMARY SERIALIZER -----
class SalesSummaryRequestSerializer(serializers.Serializer):
    filter = serializers.ChoiceField(
        choices=['day', 'month', 'year'], default='day', required=False,
    )


class SalesSummarySerializer(serializers.Serializer):
    total_success_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_penalts_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_success = serializers.IntegerField()
    total_penalts = serializers.IntegerField()
    filter_type = serializers.CharField()

# ---- CHART TREAND SERIALIZER -----
class WeeklySalesSerializer(serializers.Serializer):
    date = serializers.DateField()
    sales_amount = serializers.DecimalField(max_digits=10, decimal_places=2)


# ---- PER-ITEM SPEND SERIALIZER -----
class ItemSpendSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    item_name = serializers.CharField()
    quantity = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)


# ---- CHILD SPEND SERIALIZER -----
class ChildSpendRequestSerializer(serializers.Serializer):
    period = serializers.ChoiceField(
        choices=['week', 'month'], default='week', required=False,
    )
    start_date = serializers.DateField(required=False, allow_null=True)
    child_id = serializers.UUIDField(required=False, allow_null=True)


class ChildSpendSerializer(serializers.Serializer):
    child_id = serializers.UUIDField()
    child_name = serializers.CharField()
    class_room = serializers.CharField(required=False, allow_null=True)
    total_spend = serializers.DecimalField(max_digits=10, decimal_places=2)
    transaction_count = serializers.IntegerField()
    penalty_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    items = ItemSpendSerializer(many=True, required=False)


# ---- CHILD SPEND PERIOD WRAPPER -----
class ChildSpendPeriodSerializer(serializers.Serializer):
    period = serializers.CharField()
    start_date = serializers.DateField()
    children = ChildSpendSerializer(many=True)


# ---- LAST SESSION DETAILS -----
class LastSessionDetailsSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    session_type = serializers.CharField()
    session_status = serializers.CharField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField(allow_null=True)
    total_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    student_count = serializers.IntegerField()
    scanned_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    penalty_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    expected_cash = serializers.DecimalField(max_digits=12, decimal_places=2)
    variance = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.CharField()
