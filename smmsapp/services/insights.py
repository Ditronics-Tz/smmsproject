from datetime import timedelta

from smmsapp.models import InsightFlag, ScannedData


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
                    )
                    created += int(was_created)
    return created
