import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('smmsapp', '0015_card_uid_scan_source_and_idempotency')]

    operations = [
        migrations.CreateModel(
            name='InsightFlag',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('kind', models.CharField(default='impossible_scan', max_length=40)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('scan_a', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='insight_flags_a', to='smmsapp.scanneddata')),
                ('scan_b', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='insight_flags_b', to='smmsapp.scanneddata')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('kind', 'scan_a', 'scan_b'), name='uniq_insight_scan_pair')]},
        ),
    ]
