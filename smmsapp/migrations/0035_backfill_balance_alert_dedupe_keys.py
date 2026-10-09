import re

from django.db import migrations
from django.utils import timezone


STUDENT_MARKER = re.compile(r'\[student:([0-9a-fA-F-]{36})\]')


def backfill_low_balance_dedupe_keys(apps, schema_editor):
    Notification = apps.get_model('smmsapp', 'Notification')
    database = schema_editor.connection.alias
    seen = set(
        Notification.objects.using(database)
        .exclude(dedupe_key__isnull=True)
        .values_list('recipient_id', 'dedupe_key')
    )
    old_alerts = Notification.objects.using(database).filter(
        type='reminder', dedupe_key__isnull=True,
    ).order_by('created_at', 'pk')
    for notice in old_alerts.iterator(chunk_size=500):
        match = STUDENT_MARKER.search(notice.message or '')
        if not match or notice.created_at is None:
            continue
        alert_day = timezone.localtime(notice.created_at).date().isoformat()
        key = f'low_balance:{match.group(1)}:{alert_day}'
        unique_pair = (notice.recipient_id, key)
        # Legacy alerts were deduplicated in application code. If old duplicate
        # rows nevertheless exist, only the earliest claims the unique key.
        if unique_pair in seen:
            continue
        Notification.objects.using(database).filter(pk=notice.pk).update(dedupe_key=key)
        seen.add(unique_pair)


class Migration(migrations.Migration):
    dependencies = [('smmsapp', '0034_alter_auditlog_action')]

    operations = [migrations.RunPython(backfill_low_balance_dedupe_keys, migrations.RunPython.noop)]
