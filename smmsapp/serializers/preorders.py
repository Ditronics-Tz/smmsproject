from rest_framework import serializers

from smmsapp.models import PreOrder, PreOrderItem


class PreOrderItemSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    class Meta:
        model = PreOrderItem
        fields = ['item', 'item_name', 'quantity', 'unit_price', 'fulfilled_quantity']


class PreOrderSerializer(serializers.ModelSerializer):
    items = PreOrderItemSerializer(many=True, read_only=True)
    card_number = serializers.CharField(source='card.card_number', read_only=True)
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    class Meta:
        model = PreOrder
        fields = ['id', 'student', 'student_name', 'card', 'card_number', 'date', 'meal_type', 'status', 'total_amount', 'cutoff_at', 'items', 'created_at', 'cancelled_at', 'note']


class PreOrderItemInputSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)


class PreOrderCreateSerializer(serializers.Serializer):
    child_id = serializers.UUIDField()
    date = serializers.DateField()
    meal_type = serializers.ChoiceField(choices=['breakfast', 'lunch', 'dinner'])
    idempotency_key = serializers.CharField(max_length=128)
    items = PreOrderItemInputSerializer(many=True, allow_empty=False)


class PreOrderCancelSerializer(serializers.Serializer):
    preorder_id = serializers.UUIDField()


class PreOrderMenuItemSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    name = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    max_quantity = serializers.IntegerField()


class PreOrderMenuResponseSerializer(serializers.Serializer):
    date = serializers.DateField()
    meal_type = serializers.CharField()
    can_order = serializers.BooleanField()
    cutoff_at = serializers.DateTimeField()
    items = PreOrderMenuItemSerializer(many=True)


class PreOrderListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = PreOrderSerializer(many=True)
