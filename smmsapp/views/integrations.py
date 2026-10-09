import hashlib
import secrets

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from smmsapp.integrations.authentication import ApiKeyAuthentication
from smmsapp.integrations.throttling import IntegrationKeyThrottle
from smmsapp.models import IntegrationKey, IntegrationSyncLog, WebhookDelivery, WebhookEndpoint
from smmsapp.permissions.roles import IsAdminOnly
from smmsapp.permissions.features import FeatureEnabled
from smmsapp.services.integrations import sync_batch
from smmsapp.serializers.integrations import (
    IntegrationKeyCreateSerializer, IntegrationKeyRevokeSerializer, IntegrationKeySerializer,
    IntegrationSyncRequestSerializer, IntegrationSyncResponseSerializer, IntegrationSyncLogSerializer,
    WebhookCreateSerializer, WebhookDeliverySerializer, WebhookSerializer, WebhookUpdateSerializer,
)


class IntegrationSyncView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, FeatureEnabled('INTEGRATIONS')]
    throttle_classes = [IntegrationKeyThrottle]
    sync_kind = ""

    @extend_schema(request=IntegrationSyncRequestSerializer, responses={200: IntegrationSyncResponseSerializer, 400: None})
    def post(self, request):
        if not isinstance(request.data, dict):
            return Response({"detail": "Expected a JSON object."}, status=status.HTTP_400_BAD_REQUEST)
        dry_run = request.data.get("dry_run", False)
        if not isinstance(dry_run, bool):
            return Response({"detail": "dry_run must be a boolean."}, status=400)
        try:
            result = sync_batch(
                self.sync_kind, request.data.get("rows"), request.user.school,
                request.data.get("source_system"), dry_run,
                request.auth,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)


class StudentSyncView(IntegrationSyncView):
    sync_kind = "students"


class ParentSyncView(IntegrationSyncView):
    sync_kind = "parents"


class ClassSyncView(IntegrationSyncView):
    sync_kind = "classes"


class IntegrationKeyListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOnly, FeatureEnabled('INTEGRATIONS')]

    @extend_schema(request=None, responses={200: IntegrationKeySerializer(many=True)})
    def get(self, request):
        keys = IntegrationKey.objects.filter(created_by__school=request.user.school).order_by("-created_at")
        return Response([{
            "id": str(key.id), "name": key.name, "prefix": key.prefix,
            "last_used_at": key.last_used_at, "revoked_at": key.revoked_at,
            "created_at": key.created_at,
        } for key in keys])

    @extend_schema(request=IntegrationKeyCreateSerializer, responses={201: IntegrationKeySerializer, 400: None})
    def post(self, request):
        serializer = IntegrationKeyCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        name = serializer.validated_data["name"].strip()
        if not name:
            return Response({"detail": "name must not be blank."}, status=400)
        if request.user.school_id is None:
            return Response({"detail": "An administrator must be assigned to a school."}, status=400)
        prefix = "ik_" + secrets.token_hex(5)
        raw_key = f"smms_{prefix}_{secrets.token_urlsafe(32)}"
        key = IntegrationKey.objects.create(
            name=name, prefix=prefix,
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(), created_by=request.user,
        )
        from smmsapp.services.audit import log_action
        log_action("create", obj=key, after={"name": name, "prefix": prefix}, actor=request.user, request=request)
        return Response({"id": str(key.id), "name": key.name, "prefix": key.prefix, "api_key": raw_key}, status=201)


class IntegrationKeyRevokeView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOnly, FeatureEnabled('INTEGRATIONS')]

    @extend_schema(request=None, responses={200: IntegrationKeyRevokeSerializer})
    def post(self, request, key_id):
        key = get_object_or_404(IntegrationKey, pk=key_id, created_by__school=request.user.school)
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at"])
            from smmsapp.services.audit import log_action
            log_action("deactivate", obj=key, after={"name": key.name, "prefix": key.prefix, "revoked": True}, actor=request.user, request=request)
        return Response({"id": str(key.id), "revoked_at": key.revoked_at})


class IntegrationKeyRotateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOnly, FeatureEnabled('INTEGRATIONS')]

    @extend_schema(request=None, responses={201: IntegrationKeySerializer, 400: None})
    def post(self, request, key_id):
        key = get_object_or_404(IntegrationKey, pk=key_id, created_by__school=request.user.school)
        prefix = "ik_" + secrets.token_hex(5)
        raw_key = f"smms_{prefix}_{secrets.token_urlsafe(32)}"
        with transaction.atomic():
            key = IntegrationKey.objects.select_for_update().get(pk=key.pk)
            if key.revoked_at is not None:
                return Response({"detail": "A revoked key cannot be rotated."}, status=400)
            replacement = IntegrationKey.objects.create(
                name=key.name, prefix=prefix,
                key_hash=hashlib.sha256(raw_key.encode()).hexdigest(), created_by=request.user,
            )
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at"])
        from smmsapp.services.audit import log_action
        log_action("deactivate", obj=key, after={"name": key.name, "prefix": key.prefix, "revoked": True}, actor=request.user, request=request)
        log_action("create", obj=replacement, after={"name": replacement.name, "prefix": replacement.prefix}, actor=request.user, request=request)
        return Response({"id": str(replacement.id), "name": replacement.name,
                         "prefix": replacement.prefix, "api_key": raw_key}, status=201)


class IntegrationSyncLogView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOnly, FeatureEnabled('INTEGRATIONS')]

    @extend_schema(request=None, responses={200: IntegrationSyncLogSerializer(many=True)})
    def get(self, request):
        logs = IntegrationSyncLog.objects.filter(key__created_by__school=request.user.school).order_by("-created_at")[:100]
        return Response([{
            "id": str(row.id), "endpoint": row.endpoint, "dry_run": row.dry_run,
            "created": row.created_count, "updated": row.updated_count,
            "failed": row.failed_count, "results": row.results, "created_at": row.created_at,
        } for row in logs])


class WebhookEndpointListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOnly, FeatureEnabled('INTEGRATIONS')]
    valid_events = {"meal.purchased", "deposit.processed", "balance.low", "card.replaced"}

    @extend_schema(request=None, responses={200: WebhookSerializer(many=True)})
    def get(self, request):
        endpoints = WebhookEndpoint.objects.filter(school=request.user.school).order_by("-created_at")
        return Response([{
            "id": str(row.id), "url": row.url, "events": row.events,
            "is_active": row.is_active, "created_at": row.created_at,
        } for row in endpoints])

    @extend_schema(request=WebhookCreateSerializer, responses={201: WebhookSerializer, 400: None})
    def post(self, request):
        serializer = WebhookCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        url = serializer.validated_data["url"]
        events = serializer.validated_data["events"]
        if request.user.school_id is None:
            return Response({"detail": "Administrator must belong to a school."}, status=400)
        secret = secrets.token_urlsafe(32)
        endpoint = WebhookEndpoint.objects.create(
            school=request.user.school, url=url, secret=secret, events=events, created_by=request.user,
        )
        from smmsapp.services.audit import log_action
        log_action("create", obj=endpoint, after={"url": endpoint.url, "events": endpoint.events}, actor=request.user, request=request)
        return Response({"id": str(endpoint.id), "url": endpoint.url, "events": endpoint.events,
                         "secret": secret}, status=201)


class WebhookEndpointUpdateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOnly, FeatureEnabled('INTEGRATIONS')]

    @extend_schema(request=WebhookUpdateSerializer, responses={200: WebhookSerializer, 400: None})
    def patch(self, request, endpoint_id):
        endpoint = get_object_or_404(WebhookEndpoint, pk=endpoint_id, school=request.user.school)
        serializer = WebhookUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        for field, value in serializer.validated_data.items():
            setattr(endpoint, field, value)
        endpoint.save()
        from smmsapp.services.audit import log_action
        log_action("update", obj=endpoint, after={"url": endpoint.url, "events": endpoint.events,
                                                  "is_active": endpoint.is_active}, actor=request.user, request=request)
        return Response({"id": str(endpoint.id), "url": endpoint.url, "events": endpoint.events,
                         "is_active": endpoint.is_active})


class WebhookDeliveryListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOnly, FeatureEnabled('INTEGRATIONS')]

    @extend_schema(request=None, responses={200: WebhookDeliverySerializer(many=True)})
    def get(self, request):
        deliveries = WebhookDelivery.objects.filter(endpoint__school=request.user.school).select_related("endpoint").order_by("-created_at")[:100]
        return Response([{
            "id": str(row.id), "endpoint_id": str(row.endpoint_id), "event": row.event,
            "status_code": row.status_code, "attempts": row.attempts,
            "delivered_at": row.delivered_at, "last_error": row.last_error,
            "created_at": row.created_at,
        } for row in deliveries])

