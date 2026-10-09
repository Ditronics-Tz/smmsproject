from django.urls import path

from smmsapp.views.integrations import (
    ClassSyncView, IntegrationKeyListCreateView, IntegrationKeyRevokeView, IntegrationKeyRotateView,
    IntegrationSyncLogView, ParentSyncView, StudentSyncView,
    WebhookDeliveryListView, WebhookEndpointListCreateView, WebhookEndpointUpdateView,
)

urlpatterns = [
    path("v1/students/sync", StudentSyncView.as_view(), name="integration-students-sync"),
    path("v1/parents/sync", ParentSyncView.as_view(), name="integration-parents-sync"),
    path("v1/classes/sync", ClassSyncView.as_view(), name="integration-classes-sync"),
    path("v1/admin/keys", IntegrationKeyListCreateView.as_view(), name="integration-keys"),
    path("v1/admin/keys/<int:key_id>/revoke", IntegrationKeyRevokeView.as_view(), name="integration-key-revoke"),
    path("v1/admin/keys/<int:key_id>/rotate", IntegrationKeyRotateView.as_view(), name="integration-key-rotate"),
    path("v1/admin/webhooks", WebhookEndpointListCreateView.as_view(), name="integration-webhooks"),
    path("v1/admin/webhooks/<uuid:endpoint_id>", WebhookEndpointUpdateView.as_view(), name="integration-webhook-update"),
    path("v1/admin/webhook-deliveries", WebhookDeliveryListView.as_view(), name="integration-webhook-deliveries"),
    path("v1/admin/sync-log", IntegrationSyncLogView.as_view(), name="integration-sync-log"),
]
