from rest_framework import serializers
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError


class IntegrationSyncRequestSerializer(serializers.Serializer):
    source_system = serializers.CharField(max_length=80)
    rows = serializers.ListField(child=serializers.DictField(), max_length=500)
    dry_run = serializers.BooleanField(required=False, default=False)


class IntegrationSyncRowResultSerializer(serializers.Serializer):
    index = serializers.IntegerField()
    external_id = serializers.CharField(allow_null=True, required=False)
    status = serializers.ChoiceField(choices=["created", "updated", "failed"])
    error = serializers.CharField(required=False)


class IntegrationSyncResponseSerializer(serializers.Serializer):
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = IntegrationSyncRowResultSerializer(many=True)


class IntegrationKeyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)


class IntegrationKeySerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField(required=False)
    prefix = serializers.CharField()
    api_key = serializers.CharField(required=False, read_only=True)
    last_used_at = serializers.DateTimeField(allow_null=True, required=False)
    revoked_at = serializers.DateTimeField(allow_null=True, required=False)
    created_at = serializers.DateTimeField(required=False)


class IntegrationKeyRevokeSerializer(serializers.Serializer):
    id = serializers.CharField()
    revoked_at = serializers.DateTimeField()


class IntegrationSyncLogSerializer(serializers.Serializer):
    id = serializers.CharField()
    endpoint = serializers.CharField()
    dry_run = serializers.BooleanField()
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = serializers.ListField(child=serializers.DictField())
    created_at = serializers.DateTimeField()


class WebhookCreateSerializer(serializers.Serializer):
    url = serializers.URLField()
    events = serializers.ListField(child=serializers.ChoiceField(choices=[
        "meal.purchased", "deposit.processed", "balance.low", "card.replaced",
    ]))

    def validate_url(self, value):
        try:
            URLValidator(schemes=["https"])(value)
        except ValidationError as exc:
            raise serializers.ValidationError("Webhook URL must use HTTPS.") from exc
        return value


class WebhookSerializer(serializers.Serializer):
    id = serializers.CharField()
    url = serializers.URLField()
    events = serializers.ListField(child=serializers.CharField())
    is_active = serializers.BooleanField(required=False)
    created_at = serializers.DateTimeField(required=False)
    secret = serializers.CharField(required=False, write_only=True)


class WebhookUpdateSerializer(serializers.Serializer):
    url = serializers.URLField(required=False)
    events = serializers.ListField(child=serializers.CharField(), required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_url(self, value):
        try:
            URLValidator(schemes=["https"])(value)
        except ValidationError as exc:
            raise serializers.ValidationError("Webhook URL must use HTTPS.") from exc
        return value


class WebhookDeliverySerializer(serializers.Serializer):
    id = serializers.CharField()
    endpoint_id = serializers.CharField()
    event = serializers.CharField()
    status_code = serializers.IntegerField(allow_null=True)
    attempts = serializers.IntegerField()
    delivered_at = serializers.DateTimeField(allow_null=True)
    last_error = serializers.CharField()
    created_at = serializers.DateTimeField()
