from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from smmsapp.models import JournalEntry, JournalLine, LedgerAccount, LedgerIntegrityRun, RFIDCard, SponsorFund

WALLET_ACCOUNTS = {'2000', '2100'}
FUND_ACCOUNTS = {'2200'}


class LedgerPostingError(ValueError):
    pass


def _as_decimal(value):
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise LedgerPostingError('Journal amounts must be valid decimals.') from exc
    if not amount.is_finite() or amount <= 0:
        raise LedgerPostingError('Journal line amounts must be greater than zero.')
    return amount


def _net_for_card(account, card):
    totals = JournalLine.objects.filter(account=account, rfid_card=card).aggregate(
        credits=Sum('amount', filter=Q(direction='credit')),
        debits=Sum('amount', filter=Q(direction='debit')),
    )
    return (totals['credits'] or Decimal('0.00')) - (totals['debits'] or Decimal('0.00'))


def _net_for_fund(account, fund):
    totals = JournalLine.objects.filter(account=account, fund=fund).aggregate(
        credits=Sum('amount', filter=Q(direction='credit')),
        debits=Sum('amount', filter=Q(direction='debit')),
    )
    return (totals['credits'] or Decimal('0.00')) - (totals['debits'] or Decimal('0.00'))


def post_entry(event_type, lines, idempotency_key, refs=None, actor=None, memo=''):
    """Write a balanced, idempotent, append-only journal entry.

    Must be called from the same atomic block as the balance and source-record
    mutation. The service locks referenced cards in stable order before reading
    wallet/hold running balances.
    """
    if not connection.in_atomic_block:
        raise LedgerPostingError('post_entry must run inside transaction.atomic().')
    existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    if not lines or len(lines) < 2:
        raise LedgerPostingError('A journal entry needs at least two lines.')

    prepared = []
    debit_total = Decimal('0.00')
    credit_total = Decimal('0.00')
    cards = {}
    funds = {}
    for line in lines:
        direction = line.get('direction')
        if direction not in ('debit', 'credit'):
            raise LedgerPostingError('Each journal line must be a debit or credit.')
        amount = _as_decimal(line.get('amount'))
        account_value = line.get('account')
        account = account_value if isinstance(account_value, LedgerAccount) else LedgerAccount.objects.get(code=str(account_value))
        if not account.is_active:
            raise LedgerPostingError(f'Ledger account {account.code} is inactive.')
        card = line.get('rfid_card')
        fund = line.get('fund')
        if account.code in WALLET_ACCOUNTS and card is None:
            raise LedgerPostingError(f'Account {account.code} requires an RFID card.')
        if account.code in WALLET_ACCOUNTS and fund is not None:
            raise LedgerPostingError(f'Account {account.code} cannot carry a sponsor fund.')
        if account.code in FUND_ACCOUNTS and fund is None:
            raise LedgerPostingError(f'Account {account.code} requires a sponsor fund.')
        if account.code in FUND_ACCOUNTS and card is not None:
            raise LedgerPostingError(f'Account {account.code} cannot carry an RFID card.')
        if account.code not in WALLET_ACCOUNTS | FUND_ACCOUNTS and (card is not None or fund is not None):
            raise LedgerPostingError(f'Account {account.code} cannot carry an RFID card.')
        if card is not None:
            cards[str(card.pk)] = card
        if fund is not None:
            funds[str(fund.pk)] = fund
        prepared.append({'account': account, 'direction': direction, 'amount': amount, 'rfid_card': card, 'fund': fund})
        if direction == 'debit':
            debit_total += amount
        else:
            credit_total += amount
    if debit_total != credit_total:
        raise LedgerPostingError('Journal debits must equal credits.')

    locked_cards = {}
    for card_id in sorted(cards):
        locked_cards[card_id] = RFIDCard.objects.select_for_update().get(pk=card_id)
    for line in prepared:
        if line['rfid_card'] is not None:
            line['rfid_card'] = locked_cards[str(line['rfid_card'].pk)]
    locked_funds = {}
    for fund_id in sorted(funds):
        locked_funds[fund_id] = SponsorFund.objects.select_for_update().get(pk=fund_id)
    fund_debits = {}
    for line in prepared:
        if line['fund'] is not None:
            line['fund'] = locked_funds[str(line['fund'].pk)]
            if line['account'].code in FUND_ACCOUNTS and line['direction'] == 'debit':
                key = (line['account'].pk, line['fund'].pk)
                fund_debits[key] = fund_debits.get(key, Decimal('0.00')) + line['amount']
    for (account_id, fund_id), amount in fund_debits.items():
        account = next(line['account'] for line in prepared if line['account'].pk == account_id)
        fund = locked_funds[str(fund_id)]
        if _net_for_fund(account, fund) < amount:
            raise LedgerPostingError('Sponsor fund balance is insufficient.')

    ref_values = refs or {}
    try:
        # A savepoint lets a concurrent duplicate idempotency key safely return
        # the winner's immutable entry without breaking the caller's atomic tx.
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                event_type=event_type,
                idempotency_key=idempotency_key,
                memo=memo,
                created_by=actor,
                ref_transaction=ref_values.get('ref_transaction'),
                ref_deposit=ref_values.get('ref_deposit'),
                ref_reversal=ref_values.get('ref_reversal'),
            )
            for line in prepared:
                card = line['rfid_card']
                balance_after = None
                if line['account'].code in WALLET_ACCOUNTS:
                    balance_after = _net_for_card(line['account'], card)
                    change = line['amount'] if line['direction'] == 'credit' else -line['amount']
                    balance_after += change
                elif line['account'].code in FUND_ACCOUNTS:
                    balance_after = _net_for_fund(line['account'], line['fund'])
                    change = line['amount'] if line['direction'] == 'credit' else -line['amount']
                    balance_after += change
                JournalLine.objects.create(
                    entry=entry,
                    account=line['account'],
                    rfid_card=card,
                    fund=line['fund'],
                    direction=line['direction'],
                    amount=line['amount'],
                    balance_after=balance_after,
                )
    except IntegrityError:
        entry = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
        if entry is None:
            raise
    return entry


def post_purchase(txn, actor=None):
    amount = Decimal(txn.charged_amount)
    if amount == 0:
        return None
    return post_entry('purchase', [
        {'account': '2000', 'rfid_card': txn.rfid_card, 'direction': 'debit', 'amount': amount},
        {'account': '4000', 'direction': 'credit', 'amount': amount},
    ], f'txn:{txn.id}', refs={'ref_transaction': txn}, actor=actor, memo=f'Meal purchase: {txn.item.name}')


def post_penalty(txn, actor=None):
    amount = Decimal(txn.charged_amount)
    if amount == 0:
        return None
    return post_entry('penalty', [
        {'account': '2000', 'rfid_card': txn.rfid_card, 'direction': 'debit', 'amount': amount},
        {'account': '4100', 'direction': 'credit', 'amount': amount},
    ], f'txn:{txn.id}', refs={'ref_transaction': txn}, actor=actor, memo=f'Meal penalty: {txn.item.name}')


def post_wallet_meal(txn, wallet_meal_amount, penalty_amount=Decimal('0.00'), actor=None):
    """Post only the wallet-paid meal remainder and any wallet penalty."""
    wallet_meal_amount = Decimal(wallet_meal_amount)
    penalty_amount = Decimal(penalty_amount)
    charged = wallet_meal_amount + penalty_amount
    if charged <= 0:
        return None
    lines = [{'account': '2000', 'rfid_card': txn.rfid_card, 'direction': 'debit', 'amount': charged}]
    if wallet_meal_amount > 0:
        lines.append({'account': '4000', 'direction': 'credit', 'amount': wallet_meal_amount})
    if penalty_amount > 0:
        lines.append({'account': '4100', 'direction': 'credit', 'amount': penalty_amount})
    return post_entry('penalty' if penalty_amount else 'purchase', lines, f'txn:{txn.id}',
        refs={'ref_transaction': txn}, actor=actor, memo=f'Meal wallet payment: {txn.item.name}')


def post_deposit(deposit, actor=None):
    card = deposit.control_number
    cash_account = '1100' if deposit.payment_method == 'mobile_money' else '1000'
    return post_entry('deposit', [
        {'account': cash_account, 'direction': 'debit', 'amount': deposit.amount},
        {'account': '2000', 'rfid_card': card, 'direction': 'credit', 'amount': deposit.amount},
    ], f'deposit:{deposit.id}', refs={'ref_deposit': deposit}, actor=actor, memo='Wallet top-up')


def post_reversal(original_entry, reversal, actor=None):
    mirrored = [
        {
            'account': line.account,
            'rfid_card': line.rfid_card,
            'fund': line.fund,
            'direction': 'credit' if line.direction == 'debit' else 'debit',
            'amount': line.amount,
        }
        for line in original_entry.lines.select_related('account', 'rfid_card').all()
    ]
    return post_entry('reversal', mirrored, f'reversal:{reversal.transaction_id}:{original_entry.id}',
                      refs={'ref_reversal': reversal}, actor=actor, memo=reversal.reason)


def post_replacement(old_card, new_card, amount, actor=None):
    amount = Decimal(amount)
    if amount == 0:
        return None
    if amount > 0:
        lines = [
            {'account': '2000', 'rfid_card': old_card, 'direction': 'debit', 'amount': amount},
            {'account': '2000', 'rfid_card': new_card, 'direction': 'credit', 'amount': amount},
        ]
    else:
        amount = -amount
        lines = [
            {'account': '2000', 'rfid_card': old_card, 'direction': 'credit', 'amount': amount},
            {'account': '2000', 'rfid_card': new_card, 'direction': 'debit', 'amount': amount},
        ]
    return post_entry('card_replacement', lines, f'card-replacement:{old_card.id}:{new_card.id}', actor=actor, memo='Card balance transfer')


def post_preorder_card_transfer(old_card, new_card, amount, actor=None):
    amount = Decimal(amount)
    if amount <= 0:
        return None
    return post_entry('preorder_card_transfer', [
        {'account': '2100', 'rfid_card': old_card, 'direction': 'debit', 'amount': amount},
        {'account': '2100', 'rfid_card': new_card, 'direction': 'credit', 'amount': amount},
    ], f'preorder-card-transfer:{old_card.id}:{new_card.id}', actor=actor, memo='Pre-order hold transfer on card replacement')


def post_opening(card, actor=None):
    amount = Decimal(card.balance)
    if amount == 0:
        return None
    if amount > 0:
        lines = [
            {'account': '3000', 'direction': 'debit', 'amount': amount},
            {'account': '2000', 'rfid_card': card, 'direction': 'credit', 'amount': amount},
        ]
    else:
        amount = -amount
        lines = [
            {'account': '2000', 'rfid_card': card, 'direction': 'debit', 'amount': amount},
            {'account': '3000', 'direction': 'credit', 'amount': amount},
        ]
    return post_entry('opening', lines, f'opening:{card.id}', actor=actor, memo='Opening card balance')


def post_preorder_hold(preorder, actor=None):
    amount = Decimal(preorder.total_amount)
    return post_entry('preorder_hold', [
        {'account': '2000', 'rfid_card': preorder.card, 'direction': 'debit', 'amount': amount},
        {'account': '2100', 'rfid_card': preorder.card, 'direction': 'credit', 'amount': amount},
    ], f'preorder-hold:{preorder.id}', actor=actor, memo=f'Pre-order hold {preorder.id}')


def post_preorder_fulfil(preorder, item, actor=None):
    amount = Decimal(item.unit_price)
    return post_entry('preorder_fulfil', [
        {'account': '2100', 'rfid_card': preorder.card, 'direction': 'debit', 'amount': amount},
        {'account': '4000', 'direction': 'credit', 'amount': amount},
    ], f'preorder-fulfil:{preorder.id}:{item.item_id}', actor=actor, memo=f'Pre-order fulfilment {preorder.id}')


def post_preorder_release(preorder, amount=None, fee=Decimal('0.00'), actor=None):
    amount = Decimal(preorder.total_amount if amount is None else amount)
    fee = Decimal(fee)
    lines = [{'account': '2100', 'rfid_card': preorder.card, 'direction': 'debit', 'amount': amount}]
    if fee:
        if fee > amount:
            raise LedgerPostingError('No-show fee cannot exceed the held amount.')
        if amount > fee:
            lines.append({'account': '2000', 'rfid_card': preorder.card, 'direction': 'credit', 'amount': amount - fee})
        lines.append({'account': '4100', 'direction': 'credit', 'amount': fee})
    else:
        lines.append({'account': '2000', 'rfid_card': preorder.card, 'direction': 'credit', 'amount': amount})
    return post_entry('preorder_release', lines, f'preorder-release:{preorder.id}', actor=actor, memo=f'Pre-order release {preorder.id}')


def post_fund_contribution(contribution, actor=None):
    """Post incoming sponsor money into the fund liability account."""
    cash_account = '1100' if contribution.method == 'mobile_money' else '1000'
    entry = post_entry('fund_contribution', [
        {'account': cash_account, 'direction': 'debit', 'amount': contribution.amount},
        {'account': '2200', 'fund': contribution.fund, 'direction': 'credit', 'amount': contribution.amount},
    ], f'fund-contrib:{contribution.id}', actor=actor or contribution.recorded_by,
       memo=f'Contribution to sponsor fund {contribution.fund.name}')
    contribution.journal_entry = entry
    contribution.save(update_fields=['journal_entry'])
    return entry


def post_fund_spend(txn, fund, amount, actor=None):
    amount = _as_decimal(amount)
    return post_entry('fund_spend', [
        {'account': '2200', 'fund': fund, 'direction': 'debit', 'amount': amount},
        {'account': '4000', 'direction': 'credit', 'amount': amount},
    ], f'fund-spend:{txn.id}:{fund.id}', refs={'ref_transaction': txn}, actor=actor,
       memo=f'Sponsor fund {fund.name} meal payment')


def post_fund_spend_reversal(txn, fund, amount, reversal, actor=None):
    """Restore a reversed sponsor payment to its original fund."""
    return post_entry('fund_spend_reversal', [
        {'account': '4000', 'direction': 'debit', 'amount': amount},
        {'account': '2200', 'fund': fund, 'direction': 'credit', 'amount': amount},
    ], f'fund-spend-reversal:{reversal.id}:{fund.id}',
       refs={'ref_reversal': reversal}, actor=actor,
       memo=f'Reversal of sponsor-funded meal payment: {txn.item.name}')


def post_fund_refund(fund, amount, refund_id, method='cash', actor=None, memo='Sponsor fund refund'):
    amount = _as_decimal(amount)
    cash_account = '1100' if method == 'mobile_money' else '1000'
    return post_entry('fund_refund', [
        {'account': '2200', 'fund': fund, 'direction': 'debit', 'amount': amount},
        {'account': cash_account, 'direction': 'credit', 'amount': amount},
    ], f'fund-refund:{refund_id}', actor=actor, memo=memo)


def post_fund_transfer(source_fund, target_fund, amount, transfer_id, actor=None, memo='Sponsor fund transfer'):
    amount = _as_decimal(amount)
    return post_entry('fund_transfer', [
        {'account': '2200', 'fund': source_fund, 'direction': 'debit', 'amount': amount},
        {'account': '2200', 'fund': target_fund, 'direction': 'credit', 'amount': amount},
    ], f'fund-transfer:{transfer_id}', actor=actor, memo=memo)


def check_ledger_integrity(persist=True):
    debit_total = JournalLine.objects.filter(direction='debit').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    credit_total = JournalLine.objects.filter(direction='credit').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    global_balanced = debit_total == credit_total
    zero = Value(Decimal('0.00'), output_field=DecimalField(max_digits=14, decimal_places=2))
    card_rows = RFIDCard.objects.annotate(
        ledger_credits=Coalesce(Sum(
            'journal_lines__amount',
            filter=Q(journal_lines__account__code='2000', journal_lines__direction='credit'),
        ), zero),
        ledger_debits=Coalesce(Sum(
            'journal_lines__amount',
            filter=Q(journal_lines__account__code='2000', journal_lines__direction='debit'),
        ), zero),
    ).annotate(
        ledger_balance=ExpressionWrapper(F('ledger_credits') - F('ledger_debits'), output_field=DecimalField(max_digits=14, decimal_places=2)),
    ).annotate(
        hold_credits=Coalesce(Sum(
            'journal_lines__amount',
            filter=Q(journal_lines__account__code='2100', journal_lines__direction='credit'),
        ), zero),
        hold_debits=Coalesce(Sum(
            'journal_lines__amount',
            filter=Q(journal_lines__account__code='2100', journal_lines__direction='debit'),
        ), zero),
    ).annotate(
        ledger_held=ExpressionWrapper(F('hold_credits') - F('hold_debits'), output_field=DecimalField(max_digits=14, decimal_places=2)),
    ).filter(~Q(balance=F('ledger_balance')) | ~Q(held_balance=F('ledger_held'))).values('id', 'card_number', 'balance', 'ledger_balance', 'held_balance', 'ledger_held')
    mismatched = [{
        'card_id': str(row['id']), 'card_number': row['card_number'],
        'ledger_balance': str(row['ledger_balance']), 'card_balance': str(row['balance']),
        'ledger_held': str(row['ledger_held']), 'held_balance': str(row['held_balance']),
    } for row in card_rows]
    fund_rows = SponsorFund.objects.annotate(
        fund_credits=Coalesce(Sum(
            'journal_lines__amount',
            filter=Q(journal_lines__account__code='2200', journal_lines__direction='credit'),
        ), zero),
        fund_debits=Coalesce(Sum(
            'journal_lines__amount',
            filter=Q(journal_lines__account__code='2200', journal_lines__direction='debit'),
        ), zero),
    ).annotate(
        ledger_balance=ExpressionWrapper(F('fund_credits') - F('fund_debits'), output_field=DecimalField(max_digits=14, decimal_places=2)),
    ).filter(ledger_balance__lt=0).values('id', 'name', 'ledger_balance')
    mismatched_funds = [{
        'fund_id': str(row['id']), 'fund_name': row['name'], 'ledger_balance': str(row['ledger_balance']),
    } for row in fund_rows]
    result = {
        'status': 'ok' if global_balanced and not mismatched and not mismatched_funds else 'mismatch',
        'checked_at': None,
        'global_balanced': global_balanced,
        'mismatched_cards': mismatched,
        'mismatched_funds': mismatched_funds,
        'debits': str(debit_total),
        'credits': str(credit_total),
    }
    if not persist:
        return result
    run = LedgerIntegrityRun.objects.create(
        status=result['status'], global_balanced=global_balanced,
        mismatched_cards=mismatched, result=result,
    )
    result['checked_at'] = run.checked_at.isoformat()
    run.result = result
    run.save(update_fields=['result'])
    if result['status'] != 'ok':
        from smmsapp.models import AuditLog, CustomUser, Notification
        for admin in CustomUser.objects.filter(role='admin', is_active=True):
            Notification.objects.create(
                recipient=admin, title='Ledger integrity mismatch',
                message=f"Ledger integrity check found {len(mismatched)} card mismatch(es). Run {run.id}.",
                type='system', status='pending',
            )
        try:
            from smmsapp.services.audit import log_action
            log_action('update', obj=run, after=result)
        except Exception:
            pass
    return result
