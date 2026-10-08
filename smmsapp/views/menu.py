from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from smmsapp.models import CanteenItem, DailyMenu, DailyMenuItem, PreOrderItem
from smmsapp.permissions.features import FeatureEnabled
from smmsapp.permissions.roles import IsAdminOnly, IsOperator
from smmsapp.serializers.menu import DailyMenuSerializer, DailyMenuWriteSerializer, MenuCopySerializer
from smmsapp.services.audit import log_action, snapshot


def _save_menu_items(menu, rows):
    item_ids = [row['item_id'] for row in rows]
    if len(item_ids) != len(set(item_ids)):
        return 'Each item can appear only once in a menu.'
    items = {str(item.id): item for item in CanteenItem.objects.filter(id__in=item_ids, is_active=True)}
    if len(items) != len(item_ids):
        return 'Every menu item must be an active canteen item.'
    protected = PreOrderItem.objects.filter(
        preorder__status='placed', preorder__date=menu.date,
        preorder__meal_type=menu.meal_type,
    ).exclude(item_id__in=item_ids).exists()
    if protected:
        return 'MENU_ITEM_HAS_PREORDERS'
    DailyMenuItem.objects.filter(menu=menu).delete()
    DailyMenuItem.objects.bulk_create([
        DailyMenuItem(menu=menu, item=items[str(row['item_id'])], price_override=row.get('price_override'))
        for row in rows
    ])
    return None


class DailyMenuListCreateView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('MENU')]

    @extend_schema(tags=['menu'], responses=DailyMenuSerializer(many=True))
    def get(self, request):
        menus = DailyMenu.objects.prefetch_related('items__item').order_by('-date', 'meal_type')
        menu_date = request.query_params.get('date')
        if menu_date:
            menus = menus.filter(date=menu_date)
        return Response(DailyMenuSerializer(menus, many=True).data)

    @extend_schema(tags=['menu'], request=DailyMenuWriteSerializer, responses={201: DailyMenuSerializer})
    def post(self, request):
        serializer = DailyMenuWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if DailyMenu.objects.filter(date=values['date'], meal_type=values['meal_type']).exists():
            return Response({'code': 'DAILY_MENU_EXISTS', 'detail': 'A menu already exists for this date and meal type.'}, status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                menu = DailyMenu.objects.create(date=values['date'], meal_type=values['meal_type'], created_by=request.user)
                error = _save_menu_items(menu, values['items'])
                if error:
                    transaction.set_rollback(True)
                    code = error if error == 'MENU_ITEM_HAS_PREORDERS' else 'INVALID_MENU_ITEMS'
                    return Response({'code': code, 'detail': error}, status=status.HTTP_409_CONFLICT if code == 'MENU_ITEM_HAS_PREORDERS' else status.HTTP_400_BAD_REQUEST)
                log_action('create', obj=menu, after=snapshot(menu), actor=request.user, request=request)
        except IntegrityError:
            return Response({'code': 'DAILY_MENU_EXISTS', 'detail': 'A menu already exists for this date and meal type.'}, status=status.HTTP_409_CONFLICT)
        return Response(DailyMenuSerializer(menu).data, status=status.HTTP_201_CREATED)


class DailyMenuDetailView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('MENU')]

    @extend_schema(tags=['menu'], responses=DailyMenuSerializer)
    def get(self, request, menu_id):
        menu = get_object_or_404(DailyMenu.objects.prefetch_related('items__item'), pk=menu_id)
        return Response(DailyMenuSerializer(menu).data)

    @extend_schema(tags=['menu'], request=DailyMenuWriteSerializer, responses=DailyMenuSerializer)
    def put(self, request, menu_id):
        menu = get_object_or_404(DailyMenu.objects.prefetch_related('items__item'), pk=menu_id)
        serializer = DailyMenuWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if DailyMenu.objects.filter(date=values['date'], meal_type=values['meal_type']).exclude(pk=menu.pk).exists():
            return Response({'code': 'DAILY_MENU_EXISTS', 'detail': 'A menu already exists for this date and meal type.'}, status=status.HTTP_409_CONFLICT)
        before = snapshot(menu)
        try:
            with transaction.atomic():
                menu.date, menu.meal_type = values['date'], values['meal_type']
                menu.save(update_fields=['date', 'meal_type'])
                error = _save_menu_items(menu, values['items'])
                if error:
                    transaction.set_rollback(True)
                    code = error if error == 'MENU_ITEM_HAS_PREORDERS' else 'INVALID_MENU_ITEMS'
                    return Response({'code': code, 'detail': error}, status=status.HTTP_409_CONFLICT if code == 'MENU_ITEM_HAS_PREORDERS' else status.HTTP_400_BAD_REQUEST)
                log_action('update', obj=menu, before=before, after=snapshot(menu), actor=request.user, request=request)
        except IntegrityError:
            return Response({'code': 'DAILY_MENU_EXISTS', 'detail': 'A menu already exists for this date and meal type.'}, status=status.HTTP_409_CONFLICT)
        return Response(DailyMenuSerializer(menu).data)

    @extend_schema(tags=['menu'], responses={204: None})
    def delete(self, request, menu_id):
        menu = get_object_or_404(DailyMenu.objects.prefetch_related('items'), pk=menu_id)
        if PreOrderItem.objects.filter(preorder__status='placed', preorder__date=menu.date, preorder__meal_type=menu.meal_type).exists():
            return Response({'code': 'MENU_ITEM_HAS_PREORDERS', 'detail': 'This menu has active pre-orders.'}, status=status.HTTP_409_CONFLICT)
        before = snapshot(menu)
        menu.delete()
        log_action('delete', obj=menu, before=before, actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DailyMenuCopyView(APIView):
    permission_classes = [IsAdminOnly, FeatureEnabled('MENU')]

    @extend_schema(tags=['menu'], request=MenuCopySerializer, responses={201: DailyMenuSerializer(many=True)})
    def post(self, request):
        serializer = MenuCopySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source_date = serializer.validated_data['source_date']
        target_date = serializer.validated_data['target_date']
        if source_date == target_date:
            return Response({'code': 'INVALID_MENU_COPY', 'detail': 'Source and target dates must differ.'}, status=status.HTTP_400_BAD_REQUEST)
        source = list(DailyMenu.objects.filter(date=source_date).prefetch_related('items__item'))
        if not source:
            return Response({'code': 'DAILY_MENU_NOT_FOUND', 'detail': 'No source menus exist for that date.'}, status=status.HTTP_404_NOT_FOUND)
        if DailyMenu.objects.filter(date=target_date).exists():
            return Response({'code': 'DAILY_MENU_EXISTS', 'detail': 'Target date already has a menu.'}, status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                copied = []
                for old_menu in source:
                    menu = DailyMenu.objects.create(date=target_date, meal_type=old_menu.meal_type, created_by=request.user)
                    DailyMenuItem.objects.bulk_create([
                        DailyMenuItem(menu=menu, item=row.item, price_override=row.price_override)
                        for row in old_menu.items.all()
                    ])
                    log_action('create', obj=menu, after=snapshot(menu), actor=request.user, request=request)
                    copied.append(menu)
        except IntegrityError:
            return Response({'code': 'DAILY_MENU_EXISTS', 'detail': 'Target date already has a menu.'}, status=status.HTTP_409_CONFLICT)
        return Response(DailyMenuSerializer(copied, many=True).data, status=status.HTTP_201_CREATED)


class TodayMenuView(APIView):
    permission_classes = [IsOperator, FeatureEnabled('MENU')]

    @extend_schema(tags=['menu'], responses=DailyMenuSerializer)
    def get(self, request):
        meal_type = request.query_params.get('meal_type')
        if meal_type not in dict(DailyMenu.MEAL_TYPE_CHOICES):
            return Response({'code': 'INVALID_MEAL_TYPE', 'detail': 'A valid meal_type is required.'}, status=status.HTTP_400_BAD_REQUEST)
        menu = DailyMenu.objects.prefetch_related('items__item').filter(
            date=timezone.localdate(), meal_type=meal_type,
        ).first()
        if menu is None:
            return Response({'code': 'DAILY_MENU_NOT_FOUND', 'detail': 'No menu is available for today.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(DailyMenuSerializer(menu).data)
