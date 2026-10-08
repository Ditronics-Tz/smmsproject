import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.core.validators import MinValueValidator
from decimal import Decimal


def seed_ledger_accounts(apps, schema_editor):
    Account = apps.get_model('smmsapp', 'LedgerAccount')
    using = schema_editor.connection.alias
    for code, name, account_type in [
        ('1000', 'BANK_CASH', 'asset'),
        ('1100', 'MOBILE_MONEY_CLEARING', 'asset'),
        ('2000', 'WALLET_LIABILITY', 'liability'),
        ('2100', 'PREORDER_HOLD', 'liability'),
        ('3000', 'OPENING_BALANCE', 'equity'),
        ('4000', 'CANTEEN_REVENUE', 'income'),
        ('4100', 'PENALTY_INCOME', 'income'),
        ('5900', 'ADJUSTMENTS', 'expense'),
    ]:
        Account.objects.using(using).get_or_create(
            code=code,
            defaults={'name': name, 'type': account_type, 'is_active': True},
        )


class Migration(migrations.Migration):
    dependencies = [('smmsapp', '0018_transaction_charged_amount')]

    operations = [
        migrations.CreateModel(
            name='LedgerAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=10, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('type', models.CharField(choices=[('asset', 'Asset'), ('liability', 'Liability'), ('equity', 'Equity'), ('income', 'Income'), ('expense', 'Expense')], max_length=12)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={'ordering': ['code']},
        ),
        migrations.CreateModel(
            name='JournalEntry',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('event_type', models.CharField(max_length=40)),
                ('idempotency_key', models.CharField(max_length=200, unique=True)),
                ('memo', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('ref_deposit', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='journal_entries', to='smmsapp.bankdeposit')),
                ('ref_reversal', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='journal_entries', to='smmsapp.reversal')),
                ('ref_transaction', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='journal_entries', to='smmsapp.transaction')),
            ],
            options={'indexes': [models.Index(fields=['event_type', 'created_at'], name='smmsapp_jo_event_t_d9c399_idx')]},
        ),
        migrations.CreateModel(
            name='LedgerIntegrityRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('ok', 'OK'), ('mismatch', 'Mismatch')], max_length=10)),
                ('checked_at', models.DateTimeField(auto_now_add=True)),
                ('global_balanced', models.BooleanField(default=False)),
                ('mismatched_cards', models.JSONField(default=list)),
                ('result', models.JSONField(default=dict)),
            ],
        ),
        migrations.CreateModel(
            name='JournalLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('direction', models.CharField(choices=[('debit', 'Debit'), ('credit', 'Credit')], max_length=6)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14, validators=[MinValueValidator(Decimal('0.01'))])),
                ('balance_after', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lines', to='smmsapp.ledgeraccount')),
                ('entry', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lines', to='smmsapp.journalentry')),
                ('rfid_card', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='journal_lines', to='smmsapp.rfidcard')),
            ],
            options={'indexes': [models.Index(fields=['rfid_card', 'created_at'], name='smmsapp_jo_rfid_ca_0e7b07_idx'), models.Index(fields=['account', 'created_at'], name='smmsapp_jo_account_eb35de_idx')], 'constraints': [models.CheckConstraint(check=models.Q(('amount__gt', 0)), name='journal_line_amount_positive'), models.CheckConstraint(check=models.Q(('direction__in', ['debit', 'credit'])), name='journal_line_direction_valid')]},
        ),
        migrations.RunPython(seed_ledger_accounts, migrations.RunPython.noop),
    ]
