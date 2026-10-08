from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from smmsapp.models import FeatureFlag


class Command(BaseCommand):
    help = 'Set a feature flag override.'

    def add_arguments(self, parser):
        parser.add_argument('key')
        state = parser.add_mutually_exclusive_group(required=True)
        state.add_argument('--on', action='store_true', dest='enabled')
        state.add_argument('--off', action='store_false', dest='enabled')

    def handle(self, *args, **options):
        key = options['key']
        if key not in settings.FEATURES_DEFAULT:
            raise CommandError(f'Unknown feature key: {key}')
        flag, _ = FeatureFlag.objects.get_or_create(
            key=key,
            defaults={'enabled': settings.FEATURES_DEFAULT[key]},
        )
        flag.enabled = options['enabled']
        flag.updated_by = None
        flag.save()
        self.stdout.write(self.style.SUCCESS(f'{key}={str(flag.enabled).lower()}'))
