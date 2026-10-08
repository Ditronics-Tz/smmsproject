import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from smmsapp.models import FeatureFlag


class Command(BaseCommand):
    help = 'Apply a named customer feature profile from docs/feature-profiles.json.'

    def add_arguments(self, parser):
        parser.add_argument('name')

    def handle(self, *args, **options):
        profile_path = Path(settings.BASE_DIR) / 'docs' / 'feature-profiles.json'
        try:
            profiles = json.loads(profile_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f'Could not read feature profiles: {exc}') from exc
        profile = profiles.get(options['name'])
        if profile is None:
            raise CommandError(f"Unknown feature profile '{options['name']}'. Choose: {', '.join(sorted(profiles))}")

        enabled_keys = set(profile.get('enabled', []))
        unknown = enabled_keys - set(settings.FEATURES_DEFAULT)
        if unknown:
            raise CommandError('Profile contains unknown feature key(s): ' + ', '.join(sorted(unknown)))

        for key in settings.FEATURES_DEFAULT:
            flag, _ = FeatureFlag.objects.get_or_create(
                key=key,
                defaults={'enabled': settings.FEATURES_DEFAULT[key]},
            )
            flag.enabled = key in enabled_keys
            flag.updated_by = None
            flag.save()

        self.stdout.write(self.style.SUCCESS(
            f"Applied '{options['name']}' profile ({len(enabled_keys)} enabled): {profile.get('description', '')}"
        ))
