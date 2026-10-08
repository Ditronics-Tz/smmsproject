from decimal import Decimal

from django.db import migrations, models


def backfill_charged_amount(apps, schema_editor):
    Transaction = apps.get_model('smmsapp', 'Transaction')
    LedgerEntry = apps.get_model('smmsapp', 'LedgerEntry')
    alias = schema_editor.connection.alias
    for txn in Transaction.objects.using(alias).all().iterator():
        if txn.transaction_status == 'successful':
            charged = txn.amount
        elif txn.transaction_status == 'penalty':
            entry = LedgerEntry.objects.using(alias).filter(
                ref_transaction_id=txn.pk, event_type='penalty',
            ).order_by('-timestamp').first()
            charged = entry.balance_before - entry.balance_after if entry else Decimal('0.00')
        else:
            charged = Decimal('0.00')
        Transaction.objects.using(alias).filter(pk=txn.pk).update(charged_amount=charged)


class Migration(migrations.Migration):
    dependencies = [('smmsapp', '0017_dailymenu')]

    operations = [
        migrations.AddField(
            model_name='transaction', name='charged_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.RunPython(backfill_charged_amount, migrations.RunPython.noop),
    ]
