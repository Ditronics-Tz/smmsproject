from decimal import Decimal

from django.conf import settings
from django.utils.timezone import now

from ..models import Notification, ParentStudent, RFIDCard


def _effective_threshold(parent):
    """Resolve a parent's balance threshold: explicit value, else system default."""
    if parent.balance_threshold is not None:
        return parent.balance_threshold
    return Decimal(str(getattr(settings, 'DEFAULT_BALANCE_THRESHOLD', '1000.00')))


def _student_marker(student):
    """Stable, unique marker embedded in the reminder message so we can dedupe a
    once-per-day low-balance reminder per parent+student without extra schema."""
    return f"[student:{student.id}]"


def has_low_balance_alert_today(parent, student):
    """True if a low-balance reminder was already queued today for this parent+student."""
    return Notification.objects.filter(
        recipient=parent,
        type='reminder',
        created_at__date=now().date(),
        message__contains=_student_marker(student),
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
        if has_low_balance_alert_today(parent, student):
            continue
        Notification.objects.create(
            recipient=parent,
            title='Low Balance Reminder',
            message=(
                f"{_student_marker(student)} "
                f"Your child {student.first_name} {student.last_name}'s balance is "
                f"{rfid_card.balance}, below the minimum threshold of {threshold}. "
                f"Please top up to avoid penalties."
            ),
            status='pending',
            type='reminder',
        )
        created += 1

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
