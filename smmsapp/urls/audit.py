from django.urls import path
from ..views.audit import AuditLogListView

urlpatterns = [
    path('logs', AuditLogListView.as_view(), name='audit-logs'),
    path('logs/', AuditLogListView.as_view(), name='audit-logs-slash'),
]
