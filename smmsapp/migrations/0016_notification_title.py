# Generated by Django 5.0.6 on 2025-02-19 06:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smmsapp', '0015_alter_transaction_transaction_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='title',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
