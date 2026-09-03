import os
import logging
from django.conf import settings
from django.utils import timezone
from .base import SMSResult
from .providers import LogSMSProvider, TwilioSMSProvider, BeemSMSProvider

logger = logging.getLogger(__name__)

# Channels abstraction: Notification declares channels, SMS is one.
CRITICAL_TYPES = {"reminder", "transaction"}  # low-balance, penalty routed to SMS first

def get_sms_provider():
    name = (os.getenv("SMS_PROVIDER") or getattr(settings, "SMS_PROVIDER", "log")).lower()
    if name == "twilio":
        return TwilioSMSProvider()
    if name == "beem":
        return BeemSMSProvider()
    return LogSMSProvider()

def normalize_tz_phone(phone: str) -> str:
    if not phone:
        return phone
    p = phone.strip().replace(" ", "").replace("-", "")
    if p.startswith("0") and len(p) >= 10:
        return "+255" + p[1:]
    if p.startswith("255") and not p.startswith("+"):
        return "+" + p
    if not p.startswith("+"):
        return "+" + p
    return p

def can_send_sms(recipient) -> tuple[bool, str]:
    """Cost controls: opt-out, no phone, rate limits."""
    if not recipient.mobile_number:
        return False, "skipped_no_phone"
    if getattr(recipient, "sms_opt_out", False):
        return False, "skipped_opt_out"
    # daily per-recipient limit
    from smmsapp.models import SMSLog
    daily_limit = int(getattr(settings, "SMS_DAILY_LIMIT", 3))
    monthly_limit = int(getattr(settings, "SMS_MONTHLY_LIMIT", 1000))  # global
    today = timezone.now().date()
    sent_today = SMSLog.objects.filter(recipient=recipient, created_at__date=today, status="sent").count()
    if sent_today >= daily_limit:
        return False, "skipped_rate_limit"
    # global monthly cap (cost bound)
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    global_sent_month = SMSLog.objects.filter(created_at__gte=month_start, status="sent").count()
    if global_sent_month >= monthly_limit:
        return False, "skipped_rate_limit"
    return True, ""

def send_sms(recipient, body: str, notification=None) -> "SMSLog":
    """Create SMSLog, enforce controls, delegate to provider, update log. Always returns log."""
    from smmsapp.models import SMSLog
    body = body.strip()[:1000]
    phone_raw = recipient.mobile_number or ""
    phone = normalize_tz_phone(phone_raw)
    can, reason = can_send_sms(recipient)
    if not can:
        log = SMSLog.objects.create(
            recipient=recipient,
            notification=notification,
            phone=phone,
            body=body,
            provider=get_sms_provider().name,
            status=reason,
        )
        logger.info(f"SMS skipped {reason} for {recipient.id} {phone}")
        return log
    provider = get_sms_provider()
    log = SMSLog.objects.create(
        recipient=recipient,
        notification=notification,
        phone=phone,
        body=body,
        provider=provider.name,
        status="pending",
        segments=max(1, (len(body) + 159) // 160),
    )
    result: SMSResult = provider.send(phone, body)
    log.provider_sid = result.provider_sid
    log.error = result.error
    log.segments = result.segments
    if result.cost_estimate is not None:
        log.cost_estimate = result.cost_estimate
    log.status = "sent" if result.success else "failed"
    if result.success:
        log.sent_at = timezone.now()
    log.save(update_fields=["provider_sid", "error", "segments", "cost_estimate", "status", "sent_at"])
    logger.info(f"SMS {log.status} via {provider.name} to {phone} sid={log.provider_sid}")
    return log

def send_critical_sms(recipient, body: str, notification=None):
    """Helper for low-balance/penalty: always attempt SMS (subject to opt-out/limits), log result."""
    return send_sms(recipient, body, notification=notification)
