from rest_framework import serializers


class BalanceThresholdSerializer(serializers.Serializer):
    """Read/write a parent's low-balance threshold. A null value resets to default."""
    balance_threshold = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=0,
    )

    effective_threshold = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )
