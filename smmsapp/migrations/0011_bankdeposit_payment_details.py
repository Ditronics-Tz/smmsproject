from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smmsapp', '0010_ledgerentry_reconciliation_reversal_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankdeposit',
            name='payment_method',
            field=models.CharField(
                choices=[('cash', 'Cash'), ('mobile_money', 'Mobile money')],
                default='cash',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='bankdeposit',
            name='provider',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='bankdeposit',
            name='reference',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
