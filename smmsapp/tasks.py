import os
import logging
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
    from .services.alerts import sweep_low_balances
    created = sweep_low_balances()
    logger.info(f"Low-balance sweep complete. {created} reminder(s) created.")
    return f"{created} reminder(s) created."


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
