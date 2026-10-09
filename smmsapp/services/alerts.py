from decimal import Decimal
from datetime import date

from django.conf import settings
from django.utils import timezone

from ..models import Notification, ParentStudent, RFIDCard


def _effective_threshold(parent):
    """Resolve a parent's balance threshold: explicit value, else system default."""
    if parent.balance_threshold is not None:
        return parent.balance_threshold
    return Decimal(str(getattr(settings, 'DEFAULT_BALANCE_THRESHOLD', '1000.00')))


def _low_balance_dedupe_key(student, alert_date: date | None = None):
    alert_date = alert_date or timezone.localdate()
    return f'low_balance:{student.id}:{alert_date.isoformat()}'


def has_low_balance_alert_today(parent, student):
    """True if a low-balance reminder was already queued today for this parent+student."""
    return Notification.objects.filter(
        recipient=parent,
        dedupe_key=_low_balance_dedupe_key(student),
    ).exists()


def maybe_alert_low_balance(rfid_card, student):
    """Create a once-per-day low-balance reminder for each of the student's parents
    when the card balance is below their effective threshold.

    Returns the number of notifications created.
    """
    if student.role != 'student' or not rfid_card.is_active:
        return 0

    created = 0
    relations = ParentStudent.objects.filter(student=student).select_related('parent')
    for relation in relations:
        parent = relation.parent
        threshold = _effective_threshold(parent)
        if rfid_card.balance >= threshold:
            continue
        dedupe_key = _low_balance_dedupe_key(student)
        notif, was_created = Notification.objects.get_or_create(
            recipient=parent, dedupe_key=dedupe_key,
            defaults={
                'title': 'Low Balance Reminder',
                'message': (
                    f"Your child {student.first_name} {student.last_name}'s balance is "
                    f"{rfid_card.balance}, below the minimum threshold of {threshold}. "
                    f"Please top up to avoid penalties."
                ),
                'status': 'pending',
                'type': 'reminder',
            },
        )
        if not was_created:
            continue
        # SMS first for feature-phone parents (Tanzania): abstracted provider, cost-controlled, logged
        try:
            from .sms import send_critical_sms
            sms_body = f"SMMS: {student.first_name} {student.last_name} balance TZS {rfid_card.balance} below {threshold}. Please top up."
            send_critical_sms(parent, sms_body, notification=notif)
        except Exception:
            pass
        created += 1

    if created:
        from .webhooks import dispatch_webhook_event
        dispatch_webhook_event(student.school_id, 'balance.low', {
            'student_id': str(student.id), 'card_id': str(rfid_card.id),
            'balance': str(rfid_card.balance),
        })
    return created


def sweep_low_balances():
    """Celery sweep: remind parents for any active, below-threshold student card
    that has not already received a reminder today.

    Returns the number of notifications created.
    """
    cards = RFIDCard.objects.filter(is_active=True).select_related('student_or_staff')
    total = 0
    for card in cards:
        student = card.student_or_staff
        if student.role != 'student':
            continue
        total += maybe_alert_low_balance(card, student)
    return total
