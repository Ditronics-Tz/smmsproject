from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.conf import settings

class Command(BaseCommand):
    help = "Purge audit logs older than AUDIT_RETENTION_DAYS"

    def handle(self, *args, **options):
        from smmsapp.models import AuditLog
        days = getattr(settings, 'AUDIT_RETENTION_DAYS', 365)
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = AuditLog.objects.filter(timestamp__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} audit logs older than {cutoff}"))
