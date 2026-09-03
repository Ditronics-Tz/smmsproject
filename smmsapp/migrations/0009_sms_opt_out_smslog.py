import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smmsapp', '0008_auditlog_canteenitem_is_active'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='sms_opt_out',
            field=models.BooleanField(default=False, help_text='If true, do not send SMS (opt-out per Tanzania TCRA rules)'),
        ),
        migrations.CreateModel(
            name='SMSLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('phone', models.CharField(max_length=20)),
                ('body', models.TextField()),
                ('provider', models.CharField(default='log', max_length=30)),
                ('provider_sid', models.CharField(blank=True, max_length=128, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed'), ('skipped_opt_out', 'Skipped - Opt Out'), ('skipped_rate_limit', 'Skipped - Rate Limited'), ('skipped_no_phone', 'Skipped - No Phone')], default='pending', max_length=20)),
                ('error', models.TextField(blank=True, null=True)),
                ('segments', models.PositiveSmallIntegerField(default=1)),
                ('cost_estimate', models.DecimalField(blank=True, decimal_places=4, max_digits=8, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('notification', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sms_logs', to='smmsapp.notification')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sms_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='smslog',
            index=models.Index(fields=['recipient', 'created_at'], name='smmsapp_sms_recipie_idx'),
        ),
        migrations.AddIndex(
            model_name='smslog',
            index=models.Index(fields=['status', 'created_at'], name='smmsapp_sms_status__idx'),
        ),
    ]
