from django.db import migrations


def canonicalize_preorder_key(apps, schema_editor):
    FeatureFlag = apps.get_model('smmsapp', 'FeatureFlag')
    manager = FeatureFlag.objects.using(schema_editor.connection.alias)
    legacy = manager.filter(key='PREORDERS').first()
    if legacy is None:
        return

    canonical = manager.filter(key='PREORDER').first()
    if canonical is None:
        legacy.key = 'PREORDER'
        legacy.save(update_fields=['key'])
        return

    # Preserve an enabled legacy override rather than silently disabling the
    # preorder endpoint during rollout. The canonical row otherwise remains
    # authoritative when both records already exist.
    if legacy.enabled and not canonical.enabled:
        canonical.enabled = True
        if canonical.updated_by_id is None:
            canonical.updated_by_id = legacy.updated_by_id
        canonical.save(update_fields=['enabled', 'updated_by', 'updated_at'])
    legacy.delete()


class Migration(migrations.Migration):
    dependencies = [('smmsapp', '0035_backfill_balance_alert_dedupe_keys')]

    operations = [migrations.RunPython(canonicalize_preorder_key, migrations.RunPython.noop)]
