from django.db import transaction
from django.db.models import F
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from smmsapp.models import CanteenItem, CustomUser, Notification, StockLevel, StockMovement
from smmsapp.permissions.features import FeatureEnabled
from smmsapp.permissions.roles import IsAdminOnly
from smmsapp.serializers.stock import StockAdjustmentSerializer, StockLevelSerializer
from smmsapp.services.audit import log_action


@extend_schema(tags=['stock'], responses=StockLevelSerializer(many=True))
class StockListView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('STOCK')]

    def get(self, request):
        levels = StockLevel.objects.select_related('item').order_by('item__name')
        return Response(StockLevelSerializer(levels, many=True).data)


@extend_schema(tags=['stock'], request=StockAdjustmentSerializer, responses=StockLevelSerializer)
class StockAdjustView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('STOCK')]

    def post(self, request):
        serializer = StockAdjustmentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        with transaction.atomic():
            item = CanteenItem.objects.select_for_update().get(id=data['item_id'])
            level = StockLevel.objects.select_for_update().filter(item=item).first()
            current_quantity = level.quantity if level else 0
            new_quantity = current_quantity + data['delta']
            if new_quantity < 0:
                return Response(
                    {'code': 'STOCK_ADJUSTMENT_NEGATIVE', 'detail': 'Stock quantity cannot become negative.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if level is None:
                level = StockLevel(item=item)
            before = {'quantity': current_quantity, 'low_threshold': level.low_threshold}
            level.quantity = new_quantity
            if 'low_threshold' in data:
                level.low_threshold = data['low_threshold']
            if level.pk:
                level.save(update_fields=['quantity', 'low_threshold', 'updated_at'])
            else:
                level.save()
            if data['delta']:
                StockMovement.objects.create(
                    item=item, delta=data['delta'], reason=data['reason'], created_by=request.user,
                )
            log_action(
                'update', obj=level, before=before,
                after={'quantity': level.quantity, 'low_threshold': level.low_threshold},
                actor=request.user, request=request,
            )
        return Response(StockLevelSerializer(level).data)


def notify_low_stock():
    """Create one low-stock alert per admin, item and local day."""
    from django.utils import timezone

    today = timezone.localdate().isoformat()
    low_levels = StockLevel.objects.select_related('item').filter(quantity__lte=F('low_threshold'))
    admins = list(CustomUser.objects.filter(role='admin'))
    created = 0
    for level in low_levels:
        key = f'low_stock:{level.item_id}:{today}'
        for admin in admins:
            _, was_created = Notification.objects.get_or_create(
                recipient=admin, dedupe_key=key,
                defaults={
                    'title': 'Low stock alert',
                    'message': f'{level.item.name} stock is low ({level.quantity} remaining; threshold {level.low_threshold}).',
                    'type': 'system', 'status': 'pending',
                },
            )
            created += int(was_created)
    return created
