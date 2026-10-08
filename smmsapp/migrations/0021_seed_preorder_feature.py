from django.conf import settings
from django.db import migrations


def seed_preorder_flag(apps, schema_editor):
    FeatureFlag = apps.get_model('smmsapp', 'FeatureFlag')
    FeatureFlag.objects.using(schema_editor.connection.alias).get_or_create(
        key='PREORDER',
        defaults={'enabled': getattr(settings, 'FEATURES_DEFAULT', {}).get('PREORDER', False), 'description': 'Parent pre-orders and held balances.'},
    )


class Migration(migrations.Migration):
    dependencies = [('smmsapp', '0020_preorder_preorderitem_and_more')]
    operations = [migrations.RunPython(seed_preorder_flag, migrations.RunPython.noop)]
