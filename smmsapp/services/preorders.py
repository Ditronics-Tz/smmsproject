from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from smmsapp.models import PreOrder, PreOrderItem, RFIDCard
from smmsapp.services.ledger import post_preorder_fulfil, post_preorder_hold, post_preorder_release


def cutoff_for(order_date):
    zone = ZoneInfo(settings.PREORDER_TIME_ZONE)
    local_day = order_date - timedelta(days=1)
    hour, minute = (int(part) for part in settings.PREORDER_CUTOFF_TIME.split(':', 1))
    return timezone.make_aware(datetime.combine(local_day, time(hour, minute)), zone)


def notify_preorder(preorder, event, message):
    from smmsapp.models import Notification, ParentStudent
    for link in ParentStudent.objects.filter(student=preorder.student).select_related('parent'):
        notification, created = Notification.objects.get_or_create(
            recipient=link.parent, dedupe_key=f'preorder:{preorder.id}:{event}',
            defaults={'title': f'Pre-order {event.replace("_", " ")}', 'message': message, 'type': 'message'},
        )
        if created:
            def send_sms_after_commit(recipient=link.parent, body=message, pending_notification=notification):
                from smmsapp.services.sms import send_critical_sms
                send_critical_sms(recipient, body, notification=pending_notification)
            transaction.on_commit(send_sms_after_commit)


@transaction.atomic
def place_preorder(*, student, card, order_date, meal_type, rows, idempotency_key, actor):
    existing = PreOrder.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    card = RFIDCard.objects.select_for_update().get(pk=card.pk)
    if card.student_or_staff_id != student.id or not card.is_active:
        raise ValueError('PREORDER_CARD_INVALID')
    if card.balance < 0:
        raise ValueError('PREORDER_INSUFFICIENT_BALANCE')
    cutoff = cutoff_for(order_date)
    if timezone.now() >= cutoff:
        raise ValueError('PREORDER_CUTOFF_PASSED')
    # Locking the student's active card serializes concurrent create requests;
    # recheck the one-active-order rule after acquiring that lock.
    if PreOrder.objects.filter(
        student=student, date=order_date, meal_type=meal_type, status='placed',
    ).exists():
        raise ValueError('PREORDER_CONFLICT')
    total = Decimal('0.00')
    prepared = []
    for menu_item, quantity, price in rows:
        if quantity < 1 or quantity > settings.PREORDER_MAX_QTY_PER_ITEM:
            raise ValueError('PREORDER_QUANTITY_LIMIT')
        total += Decimal(price) * quantity
        prepared.append((menu_item, quantity, Decimal(price)))
    if card.balance < total:
        raise ValueError('PREORDER_INSUFFICIENT_BALANCE')
    preorder = PreOrder.objects.create(
        student=student, card=card, date=order_date, meal_type=meal_type,
        total_amount=total, cutoff_at=cutoff, idempotency_key=idempotency_key,
        created_by=actor,
    )
    for item, quantity, price in prepared:
        PreOrderItem.objects.create(preorder=preorder, item=item, quantity=quantity, unit_price=price)
    card.balance -= total
    card.held_balance += total
    card.save(update_fields=['balance', 'held_balance', 'updated_at'])
    post_preorder_hold(preorder, actor=actor)
    return preorder


@transaction.atomic
def release_preorder(preorder, *, status_value='cancelled', actor=None, fee=Decimal('0.00')):
    card_id = PreOrder.objects.filter(pk=preorder.pk).values_list('card_id', flat=True).first()
    if card_id is None:
        return preorder
    card = RFIDCard.objects.select_for_update().get(pk=card_id)
    preorder = PreOrder.objects.select_for_update().get(pk=preorder.pk)
    if preorder.status != 'placed':
        return preorder
    if preorder.card_id != card_id:
        card = RFIDCard.objects.select_for_update().get(pk=preorder.card_id)
    remaining = sum((row.unit_price * (row.quantity - row.fulfilled_quantity) for row in preorder.items.all()), Decimal('0.00'))
    fee = min(Decimal(fee), remaining)
    if remaining:
        card.held_balance -= remaining
        card.balance += remaining - fee
    card.save(update_fields=['balance', 'held_balance', 'updated_at'])
    if remaining:
        post_preorder_release(preorder, amount=remaining, fee=fee, actor=actor)
    preorder.status = status_value
    preorder.cancelled_at = timezone.now() if status_value == 'cancelled' else None
    preorder.save(update_fields=['status', 'cancelled_at'])
    returned = remaining - fee
    notify_preorder(preorder, status_value, f'Pre-order for {preorder.date} was {status_value.replace("_", " ")}. Amount returned: {returned:.2f}.')
    return preorder


@transaction.atomic
def fulfil_preorder_item(preorder, item, actor=None):
    card_id = PreOrder.objects.filter(pk=preorder.pk).values_list('card_id', flat=True).first()
    if card_id is None:
        return None
    card = RFIDCard.objects.select_for_update().get(pk=card_id)
    preorder = PreOrder.objects.select_for_update().get(pk=preorder.pk)
    order_item = PreOrderItem.objects.select_for_update().filter(preorder=preorder, item=item, fulfilled_quantity__lt=F('quantity')).first()
    if preorder.status != 'placed' or order_item is None:
        return None
    if preorder.card_id != card_id:
        card = RFIDCard.objects.select_for_update().get(pk=preorder.card_id)
    order_item.fulfilled_quantity += 1
    order_item.save(update_fields=['fulfilled_quantity'])
    card.held_balance -= order_item.unit_price
    card.save(update_fields=['held_balance', 'updated_at'])
    post_preorder_fulfil(preorder, order_item, actor=actor)
    if not preorder.items.filter(fulfilled_quantity__lt=F('quantity')).exists():
        preorder.status = 'fulfilled'
        preorder.save(update_fields=['status'])
    return order_item
