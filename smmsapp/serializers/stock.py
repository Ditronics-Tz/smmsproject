from rest_framework import serializers

from smmsapp.models import CanteenItem, StockLevel


class StockAdjustmentSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    delta = serializers.IntegerField()
    reason = serializers.CharField(max_length=255, allow_blank=False)
    low_threshold = serializers.IntegerField(min_value=0, required=False)

    def validate(self, attrs):
        if not CanteenItem.objects.filter(id=attrs['item_id']).exists():
            raise serializers.ValidationError({'item_id': 'Canteen item not found.'})
        if attrs['delta'] == 0 and 'low_threshold' not in attrs:
            raise serializers.ValidationError('Supply a non-zero delta or update low_threshold.')
        return attrs


class StockLevelSerializer(serializers.ModelSerializer):
    item_id = serializers.UUIDField(source='item.id', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)

    class Meta:
        model = StockLevel
        fields = ['item_id', 'item_name', 'quantity', 'low_threshold', 'updated_at']
