import os
import logging
import json
import requests
from celery import shared_task
from django.core.mail import send_mail, EmailMultiAlternatives
from django.conf import settings
from django.utils.timezone import now
from pyfcm import FCMNotification
from dotenv import load_dotenv
from .models import Notification
from django.template.loader import render_to_string

# Load .env variables
load_dotenv()

# Set logger and log to a file
logger = logging.getLogger(__name__)

file_handler = logging.FileHandler('send_pending_logs.log')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

logger.info("Script started.")


@shared_task
def build_insights():
    """Refresh scan-integrity insights; no scan pair is deleted on reruns."""
    from .services.features import is_enabled
    if not is_enabled('INSIGHTS'):
        return 0
    from .services.insights import build_all_insight_flags
    return build_all_insight_flags()


@shared_task
def check_ledger_integrity():
    from .services.ledger import check_ledger_integrity as run_check
    return run_check(persist=True)


@shared_task
def build_daily_stats(day_iso=None):
    """Build stats for the previous local day; historical snapshots are rebuildable."""
    from datetime import date, timedelta
    from django.utils import timezone
    from .services.analytics import build_daily_stats_for_day

    day = date.fromisoformat(day_iso) if day_iso else timezone.localdate() - timedelta(days=1)
    return build_daily_stats_for_day(day)


@shared_task(bind=True, max_retries=4, default_retry_delay=30)
def deliver_webhook(self, delivery_id):
    """Post a signed webhook; Celery retries failures up to five total tries."""
    from django.utils import timezone
    from .models import WebhookDelivery
    from .services.webhooks import _assert_public_https_target, webhook_signature
    from .services.features import is_enabled

    if not is_enabled("INTEGRATIONS"):
        return "feature_disabled"

    delivery = WebhookDelivery.objects.select_related("endpoint").get(pk=delivery_id)
    if delivery.delivered_at:
        return "already_delivered"
    body = json.dumps({"event": delivery.event, "data": delivery.payload}, separators=(",", ":")).encode("utf-8")
    signature = webhook_signature(delivery.endpoint.secret, body)
    delivery.attempts += 1
    try:
        _assert_public_https_target(delivery.endpoint.url)
        response = requests.post(
            delivery.endpoint.url, data=body, headers={
                "Content-Type": "application/json", "X-SMMS-Signature": signature,
                "X-SMMS-Event": delivery.event,
            }, timeout=(5, 15), allow_redirects=False,
        )
        delivery.status_code = response.status_code
        if 200 <= response.status_code < 300:
            delivery.delivered_at = timezone.now()
            delivery.last_error = ""
            delivery.save(update_fields=["attempts", "status_code", "delivered_at", "last_error"])
            return "delivered"
        delivery.last_error = f"HTTP {response.status_code}"
        delivery.save(update_fields=["attempts", "status_code", "last_error"])
        raise RuntimeError(f"Webhook returned HTTP {response.status_code}")
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        delivery.last_error = type(exc).__name__
        delivery.save(update_fields=["attempts", "status_code", "last_error"])
        if self.request.retries >= self.max_retries:
            return "failed"
        raise self.retry(exc=exc)


@shared_task
def sync_school_system():
    """Scheduled CSV/adapter import through the same idempotent sync service."""
    from django.conf import settings
    from .integrations.adapters.loader import load_school_adapter
    from .models import IntegrationKey
    from .services.integrations import sync_batch
    from .services.features import is_enabled

    if not is_enabled("INTEGRATIONS"):
        return {"configured": False, "reason": "INTEGRATIONS feature is disabled"}

    key_id = settings.SCHOOL_SYSTEM_INTEGRATION_KEY_ID
    if not key_id:
        return {"configured": False, "reason": "SCHOOL_SYSTEM_INTEGRATION_KEY_ID is unset"}
    key = IntegrationKey.objects.select_related("created_by", "created_by__school").filter(
        pk=key_id, revoked_at__isnull=True, created_by__is_active=True,
    ).first()
    if key is None or key.created_by.school_id is None:
        return {"configured": False, "reason": "Configured integration key is unavailable"}

    adapter = load_school_adapter()
    totals = {}
    for kind in ("students", "parents", "classes"):
        rows = getattr(adapter, f"fetch_{kind}")()
        totals[kind] = sync_batch(
            kind, rows, key.created_by.school, settings.SCHOOL_SYSTEM_SOURCE,
            settings.SCHOOL_SYSTEM_SYNC_DRY_RUN, key,
        )
    return {"configured": True, "results": totals}


@shared_task
def expire_preorders():
    from django.utils import timezone
    from .models import PreOrder
    from .services.preorders import release_preorder
    count = 0
    for order in PreOrder.objects.filter(status='placed', date__lt=timezone.localdate()).iterator():
        release_preorder(order, status_value='expired')
        count += 1
    return count

@shared_task
def send_pending_notifications():
    """Celery task to send pending notifications via FCM and Email."""
    logger.info("START CHECKING PENDING NOTIFICATION")

    service_account_file = os.getenv("FIREBASE_SERVICE_ACCOUNT_FILE")

    if not service_account_file:
        logger.error("FIREBASE_SERVICE_ACCOUNT_FILE environment variable is not set!")
    
    push_service = FCMNotification(service_account_file=service_account_file, project_id='smms-project-304ac')

    # Fetch all pending notifications
    pending_notifications = Notification.objects.filter(status="pending")

    if not pending_notifications.exists():
        logger.info("No pending notifications.")
        return "No pending notifications."

    for notification in pending_notifications:
        retry_count = notification.retry_count
        max_retries = 3

        while retry_count < max_retries:
            try:
                # Send Email if the recipient has an email
                if notification.recipient.email:
                    subject = f"{notification.title.upper() if notification.title else 'SMMS NOTIFICATION'}"
                    # message = notification.message
                    recipient_list = [notification.recipient.email]

                    # Load the HTML template and render it with context
                    html_content = render_to_string("email_template.html", {
                        "user": notification.recipient,
                        "notification": notification,
                        "action_url": settings.API_BASE_URL.rstrip('/') + '/admin'
                    })
                    
                    try:
                        # send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)
                        email = EmailMultiAlternatives(subject, "", settings.DEFAULT_FROM_EMAIL, recipient_list)
                        email.attach_alternative(html_content, "text/html")
                        email.send()
                        logger.info(f"Email sent successfully to {notification.recipient.email}.")
                    except Exception as e:
                        logger.error(f"Failed to send email to {notification.recipient.email}: {e}")
                        # break

                # Send push notification if FCM token is available
                if notification.recipient.fcm_token:
                    response = push_service.notify(
                        fcm_token=notification.recipient.fcm_token, 
                        notification_title=notification.title,
                        notification_body=notification.message,
                        # data_payload={"status": notification.status, "id": notification.id}
                    )
                    logger.info(f"Push Notification to {notification.recipient.first_name} sent successfully.")

                else:
                    logger.warning(f"User {notification.recipient.first_name} - {notification.recipient.mobile_number} has no FCM token.")
                    # break

                # Mark notification as sent
                notification.status = "sent"
                notification.retry_count = 0  # Reset retry count on success
                notification.save()
                break  # Exit the retry loop after success

            except Exception as e:
                retry_count += 1
                notification.retry_count = retry_count
                notification.save()
                logger.error(f"Failed to send notification to  {notification.recipient.first_name}, attempt {retry_count}: {e}")

                if retry_count >= max_retries:
                    notification.status = "failed"
                    notification.save()
                    logger.error(f"Notification {notification.id} to {notification.recipient.first_name} failed after {max_retries} attempts.")
                    break  # Exit retry loop after reaching max retries

    return "Notification processing complete."


@shared_task
def check_balance_thresholds():
    """Periodic sweep: raise low-balance reminders for students whose active card
    balance is below their parent's threshold (once per day)."""
    from .services.features import is_enabled
    if not is_enabled('PARENT_LIMITS'):
        logger.info('Skipping low-balance sweep: PARENT_LIMITS is disabled.')
        return 'Skipped: PARENT_LIMITS is disabled.'
    from .services.alerts import sweep_low_balances
    created = sweep_low_balances()
    logger.info(f"Low-balance sweep complete. {created} reminder(s) created.")
    return f"{created} reminder(s) created."


@shared_task
def check_low_stock():
    from .services.features import is_enabled
    if not is_enabled('STOCK'):
        logger.info('Skipping low-stock sweep: STOCK is disabled.')
        return 0
    from .views.stock import notify_low_stock
    return notify_low_stock()


@shared_task
def check_sponsor_funds():
    """Send deduplicated low/empty/end-date fund alerts once per day."""
    from datetime import timedelta
    from decimal import Decimal
    from django.db.models import Q, Sum
    from django.utils import timezone
    from .models import InsightFlag, JournalLine, Notification, SponsorFund, CustomUser
    from .views.sponsorship import _fund_balance

    today = timezone.localdate()
    admins = CustomUser.objects.filter(role='admin', is_active=True)
    count = 0
    for fund in SponsorFund.objects.filter(status__in=['active', 'paused']):
        balance = _fund_balance(fund)
        events = []
        if balance <= 0:
            events.append(('empty', 'Sponsor fund is empty.'))
            InsightFlag.objects.get_or_create(
                kind='fund_empty', reference_type='fund', reference_id=str(fund.pk),
                defaults={'detail': {'fund_id': fund.pk, 'fund_name': fund.name, 'balance': str(balance)}},
            )
        elif fund.alert_threshold is not None and balance <= fund.alert_threshold:
            events.append(('low', f'Balance {balance:.2f} is at or below threshold {fund.alert_threshold:.2f}.'))
        if fund.end_date and today < fund.end_date <= today + timedelta(days=7):
            events.append(('ending', f'Fund validity ends on {fund.end_date}.'))
        for event, detail in events:
            for admin in admins:
                _, created = Notification.objects.get_or_create(
                    recipient=admin, dedupe_key=f'sponsor-fund:{fund.pk}:{event}:{today.isoformat()}',
                    defaults={
                        'title': f'Sponsor fund {event}: {fund.name}',
                        'message': f'{fund.name}: {detail}', 'type': 'reminder', 'status': 'pending',
                    },
                )
                count += int(created)
    return count


@shared_task
def audit_purge():
    from datetime import timedelta
    from django.conf import settings
    from django.utils.timezone import now as tz_now
    from .models import AuditLog
    days = getattr(settings, 'AUDIT_RETENTION_DAYS', 365)
    cutoff = tz_now() - timedelta(days=days)
    deleted, _ = AuditLog.objects.filter(timestamp__lt=cutoff).delete()
    logger.info(f"Audit purge: deleted {deleted} rows older than {cutoff}")
    return deleted


@shared_task
def generate_export_task(entity, filename, user_id, filters):
    """Asynchronously build an export file and notify the requesting user.

    The download endpoint later serves the file using the signed token that was
    returned to the client at request time.
    """
    from datetime import date

    from django.shortcuts import get_object_or_404

    from .models import CustomUser, Notification
    from .views.exports import _write_export

    user = get_object_or_404(CustomUser, id=user_id)

    clean_filters = {}
    for key, value in filters.items():
        if value in (None, ''):
            clean_filters[key] = None
            continue
        if key in ('from_date', 'to_date') and isinstance(value, str):
            try:
                clean_filters[key] = date.fromisoformat(value)
            except ValueError:
                clean_filters[key] = None
        else:
            clean_filters[key] = value

    _write_export(entity, filename, user, clean_filters)

    Notification.objects.create(
        recipient=user,
        title='Export Ready',
        message=f'Your {entity} export is ready for download.',
        status='pending',
        type='reminder',
    )
    logger.info(f"Export {entity} -> {filename} generated for user {user_id}")
    return filename
