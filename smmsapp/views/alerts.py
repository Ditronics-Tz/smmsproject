from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes
from drf_spectacular.utils import extend_schema

from ..permissions.roles import IsAdminParentOrStaff
from ..permissions.features import FeatureEnabled
from ..serializers.alerts import BalanceThresholdSerializer, ParentControlsSerializer
from ..serializers.system import CodeMessageSerializer
from ..services.audit import log_action, snapshot
from ..models import BlockedItem, CanteenItem, ParentStudent, SpendingRule
from ..services.alerts import _effective_threshold


@extend_schema(
    tags=['alerts'],
    request=BalanceThresholdSerializer,
    responses={200: BalanceThresholdSerializer, 403: CodeMessageSerializer},
)
class BalanceThresholdView(APIView):
    """Parent can view and update their low-balance alert threshold.

    GET returns the effective threshold (explicit value or system default).
    PUT accepts balance_threshold (decimal) or null to reset to the default.
    """
    permission_classes = [IsAdminParentOrStaff, FeatureEnabled('PARENT_LIMITS')]

    def _enforce_parent(self, request):
        if request.user.role != 'parent':
            return Response(
                {'code': 403, 'message': 'Access denied. Only parents can configure this.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def get(self, request):
        blocked = self._enforce_parent(request)
        if blocked:
            return blocked
        serializer = BalanceThresholdSerializer({
            'balance_threshold': request.user.balance_threshold,
            'effective_threshold': _effective_threshold(request.user),
        })
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        blocked = self._enforce_parent(request)
        if blocked:
            return blocked

        serializer = BalanceThresholdSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        value = serializer.validated_data.get('balance_threshold')
        user = request.user
        # Treat an explicit integer/None from the client via SerializerField.
        before_thr = snapshot(user)
        user.balance_threshold = value
        user.save(update_fields=['balance_threshold'])
        try:
            log_action('update', obj=user, before=before_thr, after=snapshot(user))
        except Exception:
            pass

        response_serializer = BalanceThresholdSerializer({
            'balance_threshold': user.balance_threshold,
            'effective_threshold': _effective_threshold(user),
        })
        return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=['parent controls'],
    parameters=[OpenApiParameter('child_id', OpenApiTypes.UUID, required=True)],
    request=ParentControlsSerializer,
    responses={200: ParentControlsSerializer, 400: CodeMessageSerializer, 403: CodeMessageSerializer},
)
class ParentControlsView(APIView):
    """Read and replace a parent's daily cap and blocked-item list for a child."""
    permission_classes = [IsAdminParentOrStaff, FeatureEnabled('PARENT_LIMITS')]

    def _child_for_parent(self, request, child_id):
        if request.user.role != 'parent':
            return None
        return ParentStudent.objects.filter(parent=request.user, student_id=child_id).select_related('student').first()

    def get(self, request):
        child_id = request.query_params.get('child_id')
        if not child_id:
            return Response({'child_id': ['This query parameter is required.']}, status=status.HTTP_400_BAD_REQUEST)
        id_serializer = ParentControlsSerializer(data={'child_id': child_id})
        if not id_serializer.is_valid():
            return Response(id_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        if request.user.role != 'parent':
            return Response({'code': 'PARENT_REQUIRED', 'detail': 'Only a parent can manage child spending controls.'}, status=status.HTTP_403_FORBIDDEN)
        child_id = id_serializer.validated_data['child_id']
        link = self._child_for_parent(request, child_id)
        if link is None:
            return Response({'code': 'CHILD_NOT_LINKED', 'detail': 'The child is not linked to this parent.'}, status=status.HTTP_403_FORBIDDEN)
        rule = SpendingRule.objects.filter(student_id=child_id).first()
        payload = {
            'child_id': str(child_id),
            'daily_limit': rule.daily_limit if rule else None,
            'blocked_item_ids': list(BlockedItem.objects.filter(student_id=child_id).order_by('item_id').values_list('item_id', flat=True)),
        }
        return Response(ParentControlsSerializer(payload).data)

    def put(self, request):
        if request.user.role != 'parent':
            return Response({'code': 'PARENT_REQUIRED', 'detail': 'Only a parent can manage child spending controls.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = ParentControlsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        child_id = data['child_id']
        link = self._child_for_parent(request, child_id)
        if link is None:
            return Response({'code': 'CHILD_NOT_LINKED', 'detail': 'The child is not linked to this parent.'}, status=status.HTTP_403_FORBIDDEN)

        item_ids = data.get('blocked_item_ids')
        if item_ids is not None:
            existing_ids = set(CanteenItem.objects.filter(id__in=item_ids).values_list('id', flat=True))
            if existing_ids != set(item_ids):
                return Response({'blocked_item_ids': ['One or more canteen items do not exist.']}, status=status.HTTP_400_BAD_REQUEST)

        student = link.student
        old_rule = SpendingRule.objects.filter(student=student).first()
        before = {
            'daily_limit': str(old_rule.daily_limit) if old_rule and old_rule.daily_limit is not None else None,
            'blocked_item_ids': sorted(str(i) for i in BlockedItem.objects.filter(student=student).values_list('item_id', flat=True)),
        }
        with transaction.atomic():
            if 'daily_limit' in data:
                SpendingRule.objects.update_or_create(student=student, defaults={'daily_limit': data['daily_limit']})
            if item_ids is not None:
                BlockedItem.objects.filter(student=student).exclude(item_id__in=item_ids).delete()
                BlockedItem.objects.bulk_create(
                    [BlockedItem(student=student, item_id=item_id) for item_id in item_ids],
                    ignore_conflicts=True,
                )
        rule = SpendingRule.objects.filter(student=student).first()
        after = {
            'daily_limit': str(rule.daily_limit) if rule else None,
            'blocked_item_ids': sorted(str(i) for i in BlockedItem.objects.filter(student=student).values_list('item_id', flat=True)),
        }
        log_action('update', obj=student, before=before, after=after, actor=request.user, request=request)
        return Response(ParentControlsSerializer({
            'child_id': str(student.id),
            'daily_limit': rule.daily_limit if rule else None,
            'blocked_item_ids': after['blocked_item_ids'],
        }).data)
