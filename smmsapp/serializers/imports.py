from rest_framework import serializers


class ImportUploadSerializer(serializers.Serializer):
    """Body for /imports/upload: a file plus a dry-run flag."""
    dry_run = serializers.BooleanField(default=True)
    mode = serializers.ChoiceField(choices=['best_effort', 'all_or_nothing'], default='best_effort')


class ImportRowReportSerializer(serializers.Serializer):
    row_number = serializers.IntegerField()
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    card_number = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False)
    errors = serializers.ListField(child=serializers.CharField(), required=False)
    warnings = serializers.ListField(child=serializers.CharField(), required=False)
