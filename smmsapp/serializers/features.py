from rest_framework import serializers

from smmsapp.models import FeatureFlag


class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = ['key', 'enabled', 'description', 'updated_by', 'updated_at']
        read_only_fields = fields


class FeatureFlagUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
