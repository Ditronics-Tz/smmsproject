from django.conf import settings
from django.core.management.base import BaseCommand

from smmsapp.models import FeatureFlag


class Command(BaseCommand):
    help = 'List supported feature flags, current values, and deployment defaults.'

    def handle(self, *args, **options):
        rows = {flag.key: flag for flag in FeatureFlag.objects.filter(key__in=settings.FEATURES_DEFAULT)}
        self.stdout.write('KEY\tENABLED\tDEFAULT\tDESCRIPTION')
        for key, default in sorted(settings.FEATURES_DEFAULT.items()):
            flag = rows.get(key)
            enabled = flag.enabled if flag else default
            description = flag.description if flag else ''
            self.stdout.write(f'{key}\t{str(enabled).lower()}\t{str(default).lower()}\t{description}')
