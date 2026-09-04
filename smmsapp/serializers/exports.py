from rest_framework import serializers


class ExportRequestSerializer(serializers.Serializer):
    """Shared request body for export endpoints."""
    export_format = serializers.ChoiceField(
        choices=['csv', 'xlsx'], default='csv', required=False,
    )
    async_mode = serializers.BooleanField(default=False, required=False)
    from_date = serializers.DateField(required=False)
    to_date = serializers.DateField(required=False)
    status = serializers.CharField(required=False, max_length=20, allow_blank=True)
    search = serializers.CharField(required=False, max_length=255, allow_blank=True)
    class_room = serializers.CharField(required=False, max_length=255, allow_blank=True)
    active = serializers.BooleanField(required=False, default=None)
