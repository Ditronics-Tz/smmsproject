from rest_framework import generics
from rest_framework.permissions import IsAdminUser
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from ..models import AuditLog
from ..serializers.audit import AuditLogSerializer
from drf_spectacular.utils import extend_schema

@extend_schema(tags=['audit'])
class AuditLogListView(generics.ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['action','actor']
    ordering_fields = ['timestamp']
    ordering = ['-timestamp']

    def get_queryset(self):
        qs = AuditLog.objects.select_related('actor','content_type').all()
        # date filters
        request = self.request
        from_date = request.query_params.get('from')
        to_date = request.query_params.get('to')
        if from_date:
            qs = qs.filter(timestamp__date__gte=from_date)
        if to_date:
            qs = qs.filter(timestamp__date__lte=to_date)
        object_id = request.query_params.get('object_id')
        if object_id:
            qs = qs.filter(object_id=object_id)
        return qs
