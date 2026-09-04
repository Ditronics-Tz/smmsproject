from rest_framework import serializers
from ..models import AuditLog

class AuditLogSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source='actor.username', read_only=True, default=None)
    content_type_name = serializers.CharField(source='content_type.model', read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ['id','timestamp','actor','actor_username','action','content_type','content_type_name','object_id','object_repr','before','after','ip_address','path','user_agent']
        read_only_fields = fields
