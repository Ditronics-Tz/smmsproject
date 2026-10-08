from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('smmsapp', '0014_seed_supported_feature_flags')]

    operations = [
        migrations.AddField(
            model_name='rfidcard', name='uid_hex',
            field=models.CharField(blank=True, max_length=20, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='transaction', name='scan_source',
            field=models.CharField(choices=[('usb', 'USB'), ('nfc', 'NFC'), ('manual', 'Manual')], default='usb', max_length=10),
        ),
        migrations.AddField(
            model_name='scanneddata', name='scan_source',
            field=models.CharField(choices=[('usb', 'USB'), ('nfc', 'NFC'), ('manual', 'Manual')], default='usb', max_length=10),
        ),
        migrations.AddField(
            model_name='scanneddata', name='client_scan_id',
            field=models.UUIDField(blank=True, null=True, unique=True),
        ),
    ]
