from django.conf import settings
from django.db import migrations


def seed_supported_flags(apps, schema_editor):
    FeatureFlag = apps.get_model('smmsapp', 'FeatureFlag')
    manager = FeatureFlag.objects.using(schema_editor.connection.alias)
    for key, enabled in getattr(settings, 'FEATURES_DEFAULT', {}).items():
        manager.get_or_create(key=key, defaults={'enabled': enabled, 'description': ''})


class Migration(migrations.Migration):
    dependencies = [
        ('smmsapp', '0013_featureflag'),
    ]

    operations = [
        migrations.RunPython(seed_supported_flags, migrations.RunPython.noop),
    ]
