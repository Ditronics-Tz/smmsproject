import os
import logging
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.utils.timezone import now
from pyfcm import FCMNotification
from dotenv import load_dotenv
from .models import Notification

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
                    subject = f"New Notification: {notification.type}"
                    message = notification.message
                    recipient_list = [notification.recipient.email]
                    
                    try:
                        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)
                        logger.info(f"Email sent successfully to {notification.recipient.email}.")
                    except Exception as e:
                        logger.error(f"Failed to send email to {notification.recipient.email}: {e}")
                        break

                # Send push notification if FCM token is available
                if notification.recipient.fcm_token:
                    response = push_service.notify(
                        fcm_token=notification.recipient.fcm_token, 
                        notification_title=notification.type,
                        notification_body=notification.message,
                        data_payload={"status": notification.status, "id": notification.id}
                    )
                    logger.info(f"Push Notification {notification.id} sent successfully.")

                else:
                    logger.warning(f"User {notification.recipient.mobile_number} has no FCM token.")
                    break

                # Mark notification as sent
                notification.status = "sent"
                notification.retry_count = 0  # Reset retry count on success
                notification.save()
                break  # Exit the retry loop after success

            except Exception as e:
                retry_count += 1
                notification.retry_count = retry_count
                notification.save()
                logger.error(f"Failed to send notification {notification.id}, attempt {retry_count}: {e}")

                if retry_count >= max_retries:
                    notification.status = "failed"
                    notification.save()
                    logger.error(f"Notification {notification.id} failed after {max_retries} attempts.")
                    break  # Exit retry loop after reaching max retries

    return "Notification processing complete."
