from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from smmsapp.models import InsightFlag, Reconciliation, Reversal, ScannedData, BankDeposit


def build_impossible_scan_flags():
    """Create one flag per pair meeting either BE-148 impossible-scan rule."""
    scans = ScannedData.objects.select_related('rfid_card', 'session').order_by('scanned_at', 'id')
    by_card = {}
    for scan in scans.iterator():
        by_card.setdefault(scan.rfid_card_id, []).append(scan)

    created = 0
    for card_scans in by_card.values():
        for index, first in enumerate(card_scans):
            for second in card_scans[index + 1:]:
                delta = second.scanned_at - first.scanned_at
                if delta > timedelta(minutes=10):
                    break
                if first.session_id == second.session_id:
                    continue
                different_operators = first.session.operator_id != second.session.operator_id
                different_meal_types = first.session.type != second.session.type
                impossible = (
                    (different_operators and delta <= timedelta(minutes=2))
                    or (different_meal_types and delta <= timedelta(minutes=10))
                )
                if impossible:
                    _, was_created = InsightFlag.objects.get_or_create(
                        kind='impossible_scan', scan_a=first, scan_b=second,
                        defaults={
                            'reference_type': 'scan_pair',
                            'reference_id': f'{first.id}:{second.id}',
                            'detail': {
                                'scan_a': str(first.id), 'scan_b': str(second.id),
                                'card_id': str(first.rfid_card_id), 'seconds_apart': int(delta.total_seconds()),
                            },
                        },
                    )
                    created += int(was_created)
    return created


def build_operational_insight_flags():
    """Create deduplicated reversal, variance, duplicate-scan and stuck-deposit flags."""
    now = timezone.now()
    created = 0
    reversal_rows = Reversal.objects.filter(
        reversed_at__gte=now - timedelta(days=7), reversed_by__role='operator',
    ).values(
        'reversed_by_id',
    ).annotate(total=Count('id')).filter(total__gt=settings.INSIGHT_REVERSAL_LIMIT)
    for row in reversal_rows:
        operator_id = row['reversed_by_id']
        if operator_id is None:
            continue
        _, was_created = InsightFlag.objects.get_or_create(
            kind='reversal_spike', reference_type='operator', reference_id=str(operator_id),
            defaults={'detail': {'reversals_last_7_days': row['total']}},
        )
        created += int(was_created)

    large_variances = Reconciliation.objects.filter(
        Q(variance__gt=settings.INSIGHT_VARIANCE_LIMIT) |
        Q(variance__lt=-settings.INSIGHT_VARIANCE_LIMIT)
    ).select_related('session')
    for reconciliation in large_variances.iterator():
        _, was_created = InsightFlag.objects.get_or_create(
            kind='session_variance', reference_type='session', reference_id=str(reconciliation.session_id),
            defaults={'detail': {'variance': str(reconciliation.variance), 'session_id': str(reconciliation.session_id)}},
        )
        created += int(was_created)

    scans = ScannedData.objects.select_related('rfid_card').order_by('scanned_at', 'id')
    by_card = {}
    for scan in scans.iterator():
        by_card.setdefault(scan.rfid_card_id, []).append(scan)
    for card_scans in by_card.values():
        for index, first in enumerate(card_scans):
            for second in card_scans[index + 1:]:
                delta = second.scanned_at - first.scanned_at
                if delta > timedelta(seconds=60):
                    break
                _, was_created = InsightFlag.objects.get_or_create(
                    kind='duplicate_scan', scan_a=first, scan_b=second,
                    defaults={
                        'reference_type': 'scan_pair',
                        'reference_id': f'{first.id}:{second.id}',
                        'detail': {'scan_a': str(first.id), 'scan_b': str(second.id), 'seconds_apart': int(delta.total_seconds())},
                    },
                )
                created += int(was_created)

    stuck = BankDeposit.objects.filter(status='pending', created_at__lte=now - timedelta(hours=24))
    for deposit in stuck.iterator():
        _, was_created = InsightFlag.objects.get_or_create(
            kind='deposit_stuck', reference_type='deposit', reference_id=str(deposit.id),
            defaults={'detail': {'deposit_id': str(deposit.id), 'card_id': str(deposit.control_number_id), 'amount': str(deposit.amount)}},
        )
        created += int(was_created)
    return created


def build_all_insight_flags():
    return build_impossible_scan_flags() + build_operational_insight_flags()
