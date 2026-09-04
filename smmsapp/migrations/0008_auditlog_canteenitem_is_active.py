import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('smmsapp', '0007_customuser_balance_threshold'),
    ]

    operations = [
        migrations.AddField(
            model_name='canteenitem',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Soft-deactivate instead of deleting when transaction history exists'),
        ),
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('action', models.CharField(choices=[('create', 'Create'), ('update', 'Update'), ('deactivate', 'Deactivate'), ('activate', 'Activate'), ('delete', 'Delete'), ('approve', 'Approve'), ('reverse', 'Reverse'), ('replace', 'Replace'), ('login', 'Login')], max_length=20)),
                ('object_id', models.CharField(blank=True, max_length=64, null=True)),
                ('object_repr', models.CharField(blank=True, max_length=255)),
                ('before', models.JSONField(blank=True, null=True)),
                ('after', models.JSONField(blank=True, null=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('path', models.CharField(blank=True, max_length=512)),
                ('user_agent', models.CharField(blank=True, max_length=512)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_logs', to=settings.AUTH_USER_MODEL)),
                ('content_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='contenttypes.ContentType')),
            ],
            options={
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['timestamp'], name='smmsapp_aud_timesta_123456_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['actor', 'timestamp'], name='smmsapp_aud_actor_i_123457_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['action', 'timestamp'], name='smmsapp_aud_action__123458_idx'),
        ),
    ]
