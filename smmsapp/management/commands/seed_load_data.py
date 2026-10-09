import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from smmsapp.models import (
    CanteenItem, CustomUser, FundContribution, JournalEntry, JournalLine,
    LedgerAccount, PreOrder, PreOrderItem, RFIDCard, ScanSession, School,
    SponsorFund, SponsorshipAllocation, Transaction, TransactionPayment,
)
from smmsapp.services.ledger import post_fund_contribution, post_preorder_hold
from smmsapp.services.preorders import release_preorder


class Command(BaseCommand):
    help = 'Create deterministic synthetic analytics/ledger load data (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument('--students', type=int, default=2000)
        parser.add_argument('--transactions', type=int, default=100000)
        parser.add_argument('--preorders', type=int, default=200)
        parser.add_argument('--seed', type=int, default=168)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('seed_load_data is disabled unless DEBUG=True.')
        students_count, transactions_count, preorder_count = (
            options['students'], options['transactions'], options['preorders'],
        )
        if students_count < 1 or transactions_count < 1 or preorder_count < 0:
            raise CommandError('Students and transactions must be positive; preorders cannot be negative.')
        if CustomUser.objects.filter(username__startswith='load-student-').exists():
            raise CommandError('Synthetic load data already exists; use a fresh development database.')
        if options['dry_run']:
            self.stdout.write(
                f'Would create {students_count} students/cards, {transactions_count} transactions, '
                f'{preorder_count} pre-orders and balanced sponsor/ledger fixtures.'
            )
            return

        rng = random.Random(options['seed'])
        today = timezone.localdate()
        since = today - timedelta(days=182)
        with transaction.atomic():
            school = School.objects.create(name='Synthetic Load Test School')
            operator = CustomUser.objects.create_user(
                username='load-operator', role='operator', school=school, password=None,
            )
            students = [CustomUser(
                username=f'load-student-{index:05d}', first_name='Load', last_name=f'Student {index:05d}',
                role='student', school=school, class_room=f'Class {index % 20 + 1:02d}', is_active=True,
            ) for index in range(students_count)]
            CustomUser.objects.bulk_create(students, batch_size=1000)
            students = list(CustomUser.objects.filter(username__startswith='load-student-').order_by('username'))

            cards = [RFIDCard(
                card_number=f'LOAD-CARD-{index:05d}', control_number=f'LOAD-CONTROL-{index:05d}',
                student_or_staff=student, balance=Decimal('100000.00'), is_active=True,
            ) for index, student in enumerate(students)]
            RFIDCard.objects.bulk_create(cards, batch_size=1000)
            cards = list(RFIDCard.objects.filter(card_number__startswith='LOAD-CARD-').order_by('card_number'))

            items = [CanteenItem.objects.create(name=f'Load Meal {index}', price=Decimal(100 + 50 * (index % 5))) for index in range(5)]
            sessions = [ScanSession.objects.create(operator=operator, type=meal) for meal in ('breakfast', 'lunch', 'dinner')]

            opening_debit = LedgerAccount.objects.get(code='3000')
            wallet_account = LedgerAccount.objects.get(code='2000')
            income_account = LedgerAccount.objects.get(code='4000')
            journal_entries, journal_lines = [], []
            for card in cards:
                entry = JournalEntry(
                    event_type='opening', idempotency_key=f'load:opening:{card.pk}',
                    memo='Synthetic performance data opening balance', created_by=operator,
                )
                journal_entries.append(entry)
            JournalEntry.objects.bulk_create(journal_entries, batch_size=1000)
            for card, entry in zip(cards, journal_entries):
                journal_lines.extend([
                    JournalLine(entry=entry, account=opening_debit, direction='debit', amount=Decimal('100000.00')),
                    JournalLine(entry=entry, account=wallet_account, rfid_card=card, direction='credit',
                                amount=Decimal('100000.00'), balance_after=Decimal('100000.00')),
                ])
            JournalLine.objects.bulk_create(journal_lines, batch_size=5000)

            transaction_rows = []
            per_txn_prices = []
            session_choices = list(sessions)
            for index in range(transactions_count):
                student_index = rng.randrange(students_count)
                card = cards[student_index]
                item = items[rng.randrange(len(items))]
                price = item.price
                txn = Transaction(
                    student_or_staff=students[student_index], rfid_card=card, item=item,
                    amount=price, charged_amount=price, transaction_status='successful',
                    session=session_choices[rng.randrange(len(session_choices))],
                )
                txn._load_day = since + timedelta(days=rng.randrange(183))
                transaction_rows.append(txn)
                per_txn_prices.append(price)
            Transaction.objects.bulk_create(transaction_rows, batch_size=2000)
            for txn in transaction_rows:
                txn.transaction_date = timezone.make_aware(datetime.combine(
                    txn._load_day, time(hour=rng.randrange(7, 18), minute=rng.randrange(60)),
                ))
            Transaction.objects.bulk_update(transaction_rows, ['transaction_date'], batch_size=2000)

            purchase_entries = [JournalEntry(
                event_type='purchase', idempotency_key=f'load:txn:{txn.pk}',
                ref_transaction=txn, memo=f'Synthetic purchase: {txn.item.name}', created_by=operator,
            ) for txn in transaction_rows]
            JournalEntry.objects.bulk_create(purchase_entries, batch_size=2000)
            balances = [Decimal('100000.00') for _ in cards]
            purchase_lines, payment_parts = [], []
            for txn, entry, price in zip(transaction_rows, purchase_entries, per_txn_prices):
                card_index = int(txn.rfid_card.card_number.rsplit('-', 1)[1])
                balances[card_index] -= price
                purchase_lines.extend([
                    JournalLine(entry=entry, account=wallet_account, rfid_card=txn.rfid_card,
                                direction='debit', amount=price, balance_after=balances[card_index]),
                    JournalLine(entry=entry, account=income_account, direction='credit', amount=price),
                ])
                payment_parts.append(TransactionPayment(
                    transaction=txn, source='wallet', amount=price, journal_entry=entry,
                ))
            JournalLine.objects.bulk_create(purchase_lines, batch_size=5000)
            TransactionPayment.objects.bulk_create(payment_parts, batch_size=5000)
            for card, balance in zip(cards, balances):
                card.balance = balance
            RFIDCard.objects.bulk_update(cards, ['balance'], batch_size=1000)

            fund = SponsorFund.objects.create(
                name='Synthetic Load Sponsor Fund', sponsor_name='Synthetic Sponsor',
                start_date=since, created_by=operator, alert_threshold=Decimal('1000.00'),
            )
            contribution = FundContribution.objects.create(
                fund=fund, amount=Decimal('50000.00'), method='bank', reference='LOAD-SEED',
                received_at=timezone.now(), recorded_by=operator,
            )
            post_fund_contribution(contribution, actor=operator)
            SponsorshipAllocation.objects.bulk_create([
                SponsorshipAllocation(
                    fund=fund, student=student, meal_types=['breakfast', 'lunch', 'dinner'],
                    daily_cap=Decimal('500.00'), per_meal_cap=Decimal('250.00'), valid_from=since,
                ) for student in students[:min(500, students_count)]
            ], batch_size=1000)

            # Cancelled synthetic orders exercise hold/release ledger paths while
            # leaving every test card's available and held balance consistent.
            order_items = []
            for index in range(preorder_count):
                student_index = index % students_count
                card = cards[student_index]
                amount = Decimal('100.00')
                order = PreOrder.objects.create(
                    student=students[student_index], card=card, date=today - timedelta(days=1 + index % 90),
                    meal_type=('breakfast', 'lunch', 'dinner')[index % 3], status='placed',
                    total_amount=amount, cutoff_at=timezone.now(),
                    idempotency_key=f'load-preorder:{index}', created_by=operator,
                )
                PreOrderItem.objects.create(preorder=order, item=items[index % len(items)], quantity=1, unit_price=amount)
                card.balance -= amount
                card.held_balance += amount
                card.save(update_fields=['balance', 'held_balance', 'updated_at'])
                post_preorder_hold(order, actor=operator)
                release_preorder(order, status_value='cancelled', actor=operator)

        self.stdout.write(self.style.SUCCESS(
            f'Created {students_count} load students/cards, {transactions_count} transactions, '
            f'{transactions_count} payments, {preorder_count} pre-orders and sponsor data '
            'with balanced opening, purchase, contribution, and hold/release journals.'
        ))
