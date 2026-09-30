from django.urls import path
from ..views.audit import AuditLogListView, AuditLogListViewSlashAlias

urlpatterns = [
    path('logs', AuditLogListView.as_view(), name='audit-logs'),
    path('logs/', AuditLogListViewSlashAlias.as_view(), name='audit-logs-slash'),
]
