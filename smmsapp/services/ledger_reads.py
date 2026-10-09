from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum

from smmsapp.models import JournalEntry, JournalLine


WALLET_ACCOUNT = "2000"
HOLD_ACCOUNT = "2100"


def journal_entries_for_school(school):
    """Scope a school's ledger through the customer-bearing source of each entry.

    Entries are selected as whole balanced journal entries so the counterpart
    cash/revenue lines remain visible without exposing another school's rows.
    """
    return JournalEntry.objects.filter(
        Q(lines__rfid_card__student_or_staff__school=school)
        | Q(ref_transaction__student_or_staff__school=school)
        | Q(ref_deposit__control_number__student_or_staff__school=school)
        | Q(lines__fund__allocations__student__school=school)
        | Q(created_by__school=school)
    ).distinct()


def card_statement_lines(card):
    """Canonical ordered read query used by card statements and PDF exports."""
    return JournalLine.objects.filter(rfid_card=card).select_related(
        "entry", "account",
    ).order_by("created_at", "id")


def _net(lines, account_code, before=None):
    scoped = lines.filter(account__code=account_code)
    if before is not None:
        scoped = scoped.filter(created_at__date__lt=before)
    totals = scoped.aggregate(
        credits=Sum("amount", filter=Q(direction="credit")),
        debits=Sum("amount", filter=Q(direction="debit")),
    )
    return (totals["credits"] or Decimal("0.00")) - (totals["debits"] or Decimal("0.00"))


def statement_period(card, start, end):
    """Build a date-bounded card statement directly from immutable journal lines."""
    lines = card_statement_lines(card)
    opening_wallet = _net(lines, WALLET_ACCOUNT, start)
    opening_held = _net(lines, HOLD_ACCOUNT, start)
    period = lines.filter(created_at__date__gte=start, created_at__date__lte=end).order_by("created_at", "id")
    wallet = opening_wallet
    held = opening_held
    rows = []
    for line in period:
        delta = line.amount if line.direction == "credit" else -line.amount
        if line.account.code == WALLET_ACCOUNT:
            wallet += delta
        elif line.account.code == HOLD_ACCOUNT:
            held += delta
        rows.append({
            "time": line.created_at,
            "event": line.entry.event_type,
            "memo": line.entry.memo,
            "account": line.account.code,
            "account_name": line.account.name,
            "direction": line.direction,
            "amount": line.amount,
            "wallet_balance": wallet,
            "held_balance": held,
        })
    return {
        "opening_balance": opening_wallet,
        "closing_balance": wallet,
        "opening_held_balance": opening_held,
        "closing_held_balance": held,
        "lines": rows,
    }


def add_months(value: date, months: int) -> date:
    """Calendar-month addition with end-of-month clamping."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))
