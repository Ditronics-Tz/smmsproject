from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_feature_flags(apps, schema_editor):
    FeatureFlag = apps.get_model('smmsapp', 'FeatureFlag')
    defaults = getattr(settings, 'FEATURES_DEFAULT', {})
    FeatureFlag.objects.using(schema_editor.connection.alias).bulk_create([
        FeatureFlag(key=key, enabled=bool(enabled), description='')
        for key, enabled in defaults.items()
    ], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ('smmsapp', '0012_passwordresettoken_purpose'),
    ]

    operations = [
        migrations.CreateModel(
            name='FeatureFlag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=100, unique=True)),
                ('enabled', models.BooleanField(default=False)),
                ('description', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_feature_flags', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['key']},
        ),
        migrations.RunPython(seed_feature_flags, migrations.RunPython.noop),
    ]
