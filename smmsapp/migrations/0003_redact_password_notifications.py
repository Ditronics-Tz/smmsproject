from django.db import migrations


def redact_password_notifications(apps, schema_editor):
    """Scrub historically stored plaintext passwords from Notification messages.

    Prior to this fix, user-creation and password-reset flows stored generated
    plaintext passwords inside ``Notification.message``. This rewrites each such
    row to a sanitized message that no longer contains the password.
    """
    Notification = apps.get_model('smmsapp', 'Notification')

    # Matches the two plaintext-password notification templates:
    # 1. Forget/reset: "...your password was reset successfully. Your new password is <pw>."
    # 2. User creation: "...Use username <u> and password <pw>."
    password_templates = [
        ('your password was reset successfully', 'Your password was reset successfully. Your temporary password was sent to your email.'),
        ('Use username', 'Your account credentials were sent to your email.'),
    ]

    for needle, replacement in password_templates:
        Notification.objects.filter(message__icontains=needle).update(message=replacement)


class Migration(migrations.Migration):

    dependencies = [
        ('smmsapp', '0002_alter_transaction_transaction_status'),
    ]

    operations = [
        migrations.RunPython(redact_password_notifications, migrations.RunPython.noop),
    ]
