import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from smmsapp.models import ControlNumberCounter, RFIDCard


_UID_LENGTHS = {8, 14, 20}  # 4, 7, or 10 bytes, represented as hexadecimal.


def normalize_uid(value):
    """Normalize a phone/reader UID to uppercase hexadecimal without separators.

    Byte-order conversion is intentionally not performed until the physical
    USB-vs-phone investigation establishes that it is required.
    """
    if value is None:
        raise ValueError('UID is required')
    normalized = re.sub(r'[:\-\s]', '', str(value)).upper()
    if len(normalized) not in _UID_LENGTHS or not re.fullmatch(r'[0-9A-F]+', normalized):
        raise ValueError('UID must be 4, 7, or 10 bytes of hexadecimal')
    return normalized


class ControlNumberError(RuntimeError):
    """Raised when no unique control number can be allocated safely."""


def generate_control_number(school):
    """Allocate a monotonic per-school, per-month control number.

    The counter row lock serializes callers on PostgreSQL. ``get_or_create``
    handles the first-use race; the second query explicitly locks the row.
    Existing legacy identifiers are skipped without reusing a sequence value.
    """
    school_number = school.number
    if school_number is None or not 10 <= school_number <= 99:
        raise ControlNumberError('A school number from 10 through 99 is required.')
    yymm = timezone.localdate().strftime('%y%m')
    with transaction.atomic():
        ControlNumberCounter.objects.get_or_create(school=school, yymm=yymm)
        counter = ControlNumberCounter.objects.select_for_update().get(school=school, yymm=yymm)
        for _ in range(1000000):
            if counter.last_value >= 999999:
                raise ControlNumberError(f'Control-number sequence exhausted for school {school_number} in {yymm}.')
            counter.last_value += 1
            candidate = f'{school_number:02d}{yymm}{counter.last_value:06d}'
            if not RFIDCard.objects.filter(control_number=candidate).exists():
                counter.save(update_fields=['last_value'])
                return candidate
        raise ControlNumberError('Could not allocate an unused control number.')


def _is_control_number_conflict(error):
    cause = error.__cause__
    constraint_name = getattr(getattr(cause, 'diag', None), 'constraint_name', '') or ''
    message = f'{constraint_name} {error}'.lower()
    return 'control_number' in message and ('unique' in message or 'duplicate' in message)


def create_card_with_control_number(*, school, **fields):
    """Create a card, retrying only a control-number unique-key race (max 5)."""
    for attempt in range(5):
        fields['control_number'] = generate_control_number(school)
        try:
            with transaction.atomic():
                return RFIDCard.objects.create(**fields)
        except IntegrityError as error:
            if not _is_control_number_conflict(error) or attempt == 4:
                if _is_control_number_conflict(error):
                    raise ControlNumberError('Could not allocate a unique control number after five attempts.') from error
                raise
    raise ControlNumberError('Could not allocate a unique control number after five attempts.')
