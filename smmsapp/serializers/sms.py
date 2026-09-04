from rest_framework import serializers
from ..models import SMSLog

class SMSLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SMSLog
        fields = ["id","recipient","phone","body","provider","provider_sid","status","error","segments","cost_estimate","created_at","sent_at"]
        read_only_fields = fields
