"""Compatibility writes to the retired LedgerEntry table during UI cutover."""

from django.conf import settings

from smmsapp.models import LedgerEntry


def record_legacy_ledger_entry(**fields):
    """Dual-write only while the deployment still relies on the legacy ledger.

    The flag defaults on so existing deployments keep their current behavior.
    Do not disable it until the frontend statement screens use the journal API.
    """
    if not getattr(settings, 'LEDGER_LEGACY_WRITE', True):
        return None
    return LedgerEntry.objects.create(**fields)
