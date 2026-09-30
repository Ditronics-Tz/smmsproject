"""Serializers for ad-hoc API payloads that do not map 1:1 to a model.

Used by @extend_schema on plain APIViews so the generated OpenAPI schema
describes their real responses instead of being omitted.
"""
from rest_framework import serializers


class CodeMessageSerializer(serializers.Serializer):
    """The app-wide `{code, message}` envelope, used for both success and errors.

    `code` is optional because a handful of legacy endpoints return a bare
    `{"message": ...}` or `{"error": ...}` with no code. Those are documented
    with MessageSerializer / ErrorSerializer instead, so `code` being optional
    here only reflects the endpoints that use this envelope inconsistently.
    """
    code = serializers.IntegerField(
        required=False, help_text='HTTP status, repeated in the body',
    )
    message = serializers.CharField()


class MessageSerializer(serializers.Serializer):
    """Legacy success shape with no code, e.g. password change and logout."""
    message = serializers.CharField()


class ErrorSerializer(serializers.Serializer):
    """Legacy error shape that reports under `error` rather than `message`."""
    error = serializers.CharField()


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()


class DependencyCheckSerializer(serializers.Serializer):
    status = serializers.CharField()
    latency_ms = serializers.FloatField(required=False)
    error = serializers.CharField(required=False)
    reason = serializers.CharField(required=False)


class StatusSerializer(serializers.Serializer):
    status = serializers.CharField()
    checks = serializers.DictField(child=DependencyCheckSerializer())
