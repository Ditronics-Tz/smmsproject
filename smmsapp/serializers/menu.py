from rest_framework import serializers
from decimal import Decimal

from smmsapp.models import DailyMenu, DailyMenuItem


class DailyMenuItemInputSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    price_override = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)


class DailyMenuWriteSerializer(serializers.Serializer):
    date = serializers.DateField()
    meal_type = serializers.ChoiceField(choices=DailyMenu.MEAL_TYPE_CHOICES)
    items = DailyMenuItemInputSerializer(many=True, allow_empty=False)


class DailyMenuItemSerializer(serializers.ModelSerializer):
    item_id = serializers.UUIDField(source='item.id', read_only=True)
    name = serializers.CharField(source='item.name', read_only=True)
    price = serializers.SerializerMethodField()

    class Meta:
        model = DailyMenuItem
        fields = ['item_id', 'name', 'price', 'price_override']

    def get_price(self, obj) -> Decimal:
        return obj.price_override if obj.price_override is not None else obj.item.price


class DailyMenuSerializer(serializers.ModelSerializer):
    items = DailyMenuItemSerializer(many=True, read_only=True)

    class Meta:
        model = DailyMenu
        fields = ['id', 'date', 'meal_type', 'items', 'created_at']


class MenuCopySerializer(serializers.Serializer):
    source_date = serializers.DateField()
    target_date = serializers.DateField()
