from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from smmsapp.models import (CustomUser, DailyMenu, DailyMenuItem, Notification,
    ParentStudent, PreOrder, PreOrderItem, RFIDCard, ScanSession, Transaction)
from smmsapp.permissions.features import FeatureEnabled
from smmsapp.permissions.roles import IsAdminOrOperator
from smmsapp.serializers.preorders import (
    PreOrderCancelSerializer, PreOrderCreateSerializer, PreOrderListResponseSerializer,
    PreOrderMenuResponseSerializer, PreOrderSerializer,
)
from smmsapp.services.audit import log_action, snapshot
from smmsapp.services.preorders import cutoff_for, fulfil_preorder_item, notify_preorder, place_preorder, release_preorder


def _parse_day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _owned_student(user, student_id):
    if user.role == 'admin':
        return CustomUser.objects.filter(pk=student_id, role='student').first()
    link = ParentStudent.objects.filter(parent=user, student_id=student_id).select_related('student').first()
    return link.student if link else None


class PreOrderMenuView(APIView):
    permission_classes = [IsAuthenticated, FeatureEnabled('PREORDER')]
    @extend_schema(tags=['preorders'], responses=PreOrderMenuResponseSerializer)
    def get(self, request):
        day = _parse_day(request.query_params.get('date'))
        child_id = request.query_params.get('child_id')
        if not day or not child_id:
            return Response({'code': 'INVALID_PREORDER_REQUEST', 'detail': 'date and child_id are required.'}, status=400)
        student = _owned_student(request.user, child_id) if request.user.role in ('parent', 'admin') else None
        if student is None:
            return Response({'code': 'CHILD_NOT_FOUND', 'detail': 'Child not found or not linked to this parent.'}, status=404)
        meal_type = request.query_params.get('meal_type', 'lunch')
        menu = DailyMenu.objects.filter(date=day, meal_type=meal_type).first()
        cutoff = cutoff_for(day)
        items = []
        if menu:
            for row in menu.items.select_related('item').filter(item__is_active=True):
                items.append({'item_id': str(row.item_id), 'name': row.item.name,
                    'price': str(row.price_override if row.price_override is not None else row.item.price),
                    'max_quantity': settings.PREORDER_MAX_QTY_PER_ITEM})
        return Response({'date': day.isoformat(), 'meal_type': meal_type, 'can_order': bool(menu and timezone.now() < cutoff and day <= timezone.localdate() + timedelta(days=settings.PREORDER_MAX_DAYS_AHEAD)), 'cutoff_at': cutoff.isoformat(), 'items': items})


class PreOrderCreateView(APIView):
    permission_classes = [IsAuthenticated, FeatureEnabled('PREORDER')]
    @extend_schema(tags=['preorders'], request=PreOrderCreateSerializer, responses={201: PreOrderSerializer, 200: PreOrderSerializer})
    def post(self, request):
        if request.user.role != 'parent':
            return Response({'code': 'PERMISSION_DENIED', 'detail': 'Parent access is required.'}, status=403)
        student = _owned_student(request.user, request.data.get('child_id'))
        if student is None:
            return Response({'code': 'CHILD_NOT_FOUND', 'detail': 'Child not found or not linked to this parent.'}, status=404)
        day = _parse_day(request.data.get('date'))
        meal_type = request.data.get('meal_type')
        key = str(request.data.get('idempotency_key') or '').strip()
        if not day or not key or meal_type not in dict(ScanSession.SESSION_TYPE_CHOICES):
            return Response({'code': 'INVALID_PREORDER_REQUEST', 'detail': 'Valid date, meal_type and idempotency_key are required.'}, status=400)
        if day < timezone.localdate() or day > timezone.localdate() + timedelta(days=settings.PREORDER_MAX_DAYS_AHEAD):
            return Response({'code': 'PREORDER_DATE_OUT_OF_RANGE', 'detail': 'Date is outside the preorder window.'}, status=400)
        existing = PreOrder.objects.filter(idempotency_key=key).first()
        if existing:
            if existing.student_id != student.id:
                return Response({'code': 'IDEMPOTENCY_KEY_CONFLICT', 'detail': 'This key belongs to a different order.'}, status=409)
            return Response(PreOrderSerializer(existing).data, status=200)
        menu = DailyMenu.objects.filter(date=day, meal_type=meal_type).first()
        if menu is None:
            return Response({'code': 'PREORDER_NO_MENU', 'detail': 'No menu exists for that date and meal.'}, status=400)
        rows = request.data.get('items')
        if not isinstance(rows, list) or not rows:
            return Response({'code': 'INVALID_PREORDER_ITEMS', 'detail': 'At least one menu item is required.'}, status=400)
        menu_lines = {str(row.item_id): row for row in DailyMenuItem.objects.filter(menu=menu).select_related('item')}
        prepared = []
        seen = set()
        try:
            for requested in rows:
                item_id, quantity = str(requested.get('item_id')), int(requested.get('quantity', 0))
                line = menu_lines.get(item_id)
                if not line or item_id in seen:
                    return Response({'code': 'PREORDER_ITEM_NOT_ON_MENU', 'detail': 'Items must be unique and belong to the menu.'}, status=400)
                seen.add(item_id)
                price = line.price_override if line.price_override is not None else line.item.price
                prepared.append((line.item, quantity, price))
        except (AttributeError, TypeError, ValueError):
            return Response({'code': 'INVALID_PREORDER_ITEMS', 'detail': 'Invalid item or quantity.'}, status=400)
        card = RFIDCard.objects.filter(student_or_staff=student, is_active=True).order_by('-created_at').first()
        if card is None:
            return Response({'code': 'PREORDER_CARD_INVALID', 'detail': 'No active card is available.'}, status=400)
        try:
            preorder = place_preorder(student=student, card=card, order_date=day, meal_type=meal_type, rows=prepared, idempotency_key=key, actor=request.user)
        except ValueError as exc:
            return Response({'code': str(exc), 'detail': str(exc).replace('_', ' ').lower()}, status=400)
        except IntegrityError:
            preorder = PreOrder.objects.filter(idempotency_key=key, student=student).first()
            if preorder is not None:
                return Response(PreOrderSerializer(preorder).data, status=200)
            preorder = PreOrder.objects.filter(student=student, date=day, meal_type=meal_type, status='placed').first()
            if preorder is None:
                return Response({'code': 'PREORDER_CONFLICT', 'detail': 'Order could not be placed.'}, status=409)
            return Response(PreOrderSerializer(preorder).data, status=409)
        log_action('create', obj=preorder, after=snapshot(preorder), actor=request.user, request=request)
        notify_preorder(preorder, 'placed')
        return Response(PreOrderSerializer(preorder).data, status=201)


class PreOrderCancelView(APIView):
    permission_classes = [IsAuthenticated, FeatureEnabled('PREORDER')]
    @extend_schema(tags=['preorders'], request=PreOrderCancelSerializer, responses=PreOrderSerializer)
    def post(self, request):
        preorder = get_object_or_404(PreOrder.objects.select_related('student', 'card'), pk=request.data.get('preorder_id'))
        if request.user.role != 'admin' and not (request.user.role == 'parent' and ParentStudent.objects.filter(parent=request.user, student=preorder.student).exists()):
            return Response({'code': 'PERMISSION_DENIED', 'detail': 'You cannot cancel this order.'}, status=403)
        if preorder.status != 'placed' or timezone.now() >= preorder.cutoff_at:
            return Response({'code': 'PREORDER_NOT_CANCELLABLE', 'detail': 'Order can no longer be cancelled.'}, status=400)
        before = snapshot(preorder)
        preorder = release_preorder(preorder, actor=request.user)
        log_action('update', obj=preorder, before=before, after=snapshot(preorder), actor=request.user, request=request)
        return Response(PreOrderSerializer(preorder).data)


class PreOrderListView(APIView):
    permission_classes = [IsAuthenticated, FeatureEnabled('PREORDER')]
    @extend_schema(tags=['preorders'], responses=PreOrderListResponseSerializer)
    def get(self, request):
        orders = PreOrder.objects.select_related('student', 'card').prefetch_related('items__item')
        if request.user.role == 'parent':
            orders = orders.filter(student__parents__parent=request.user)
        elif request.user.role != 'admin':
            return Response({'code': 'PERMISSION_DENIED', 'detail': 'Parent or admin access is required.'}, status=403)
        if request.query_params.get('status'):
            orders = orders.filter(status=request.query_params['status'])
        if request.query_params.get('date'):
            orders = orders.filter(date=request.query_params['date'])
        if request.query_params.get('child_id') and request.user.role == 'parent':
            orders = orders.filter(student_id=request.query_params['child_id'])
        try:
            page = max(1, int(request.query_params.get('page', '1')))
            size = min(max(1, int(request.query_params.get('page_size', '50'))), 100)
        except ValueError:
            return Response({'code': 'INVALID_PAGINATION', 'detail': 'page and page_size must be positive integers.'}, status=400)
        total = orders.count()
        results = orders.order_by('-created_at')[(page - 1) * size:page * size]
        return Response({'count': total, 'results': PreOrderSerializer(results, many=True).data})


class PreOrderSummaryView(APIView):
    permission_classes = [IsAdminOrOperator, FeatureEnabled('PREORDER')]
    @extend_schema(tags=['preorders'], responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        day = _parse_day(request.query_params.get('date'))
        if not day:
            return Response({'code': 'INVALID_PREORDER_REQUEST', 'detail': 'date is required.'}, status=400)
        orders = PreOrder.objects.filter(date=day, status='placed').prefetch_related('items__item', 'student')
        summary = {}
        for order in orders:
            meal = summary.setdefault(order.meal_type, {'items': {}, 'students': []})
            meal['students'].append({'student_id': str(order.student_id), 'name': order.student.get_full_name(), 'items': [{'name': row.item.name, 'quantity': row.quantity} for row in order.items.all()]})
            for row in order.items.all():
                item = meal['items'].setdefault(str(row.item_id), {'name': row.item.name, 'quantity': 0})
                item['quantity'] += row.quantity - row.fulfilled_quantity
        return Response({'date': day.isoformat(), 'meals': summary})


class PreOrderSessionView(APIView):
    permission_classes = [IsAdminOrOperator, FeatureEnabled('PREORDER')]
    @extend_schema(tags=['preorders'], responses=PreOrderSerializer(many=True))
    def get(self, request):
        session = get_object_or_404(ScanSession, pk=request.query_params.get('session_id'))
        if request.user.role == 'operator' and session.operator_id != request.user.id:
            return Response({'code': 'PERMISSION_DENIED', 'detail': 'This session belongs to another operator.'}, status=403)
        orders = PreOrder.objects.filter(date=timezone.localdate(), meal_type=session.type, status='placed').prefetch_related('items__item')
        return Response(PreOrderSerializer(orders, many=True).data)
