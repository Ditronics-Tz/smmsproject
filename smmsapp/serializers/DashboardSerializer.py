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