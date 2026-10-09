from django.db import migrations


def seed_sponsor_fund_account(apps, schema_editor):
    Account = apps.get_model('smmsapp', 'LedgerAccount')
    Account.objects.using(schema_editor.connection.alias).get_or_create(
        code='2200',
        defaults={'name': 'SPONSOR_FUND_LIABILITY', 'type': 'liability', 'is_active': True},
    )


class Migration(migrations.Migration):
    dependencies = [('smmsapp', '0028_sponsorfund_fundcontribution_journalline_fund_and_more')]
    operations = [migrations.RunPython(seed_sponsor_fund_account, migrations.RunPython.noop)]
