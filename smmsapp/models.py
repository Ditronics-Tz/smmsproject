from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q, CheckConstraint
from django.db.models.signals import pre_save
from django.dispatch import receiver
from decimal import Decimal
import uuid
import os

# The lowest allowed balance for an RFID card. An insufficient-balance meal
# applies a -500 penalty, and this floor is the maximum distance a single
# penalty or deduction may push a balance below zero. It is enforced both in
# the model (validators + DB CHECK constraint) so no code path, admin action,
# or script can drive a card arbitrarily negative.
RFID_BALANCE_FLOOR = Decimal(settings.RFID_BALANCE_FLOOR)

# --- function to save profile image
def user_profile_path(instance, filename):
    """Generate file path for profile picture"""
    ext = filename.split('.')[-1]

    if instance.role == 'student':
        filename = f"student_pics/{instance.first_name}_{instance.middle_name}_{instance.last_name}.{ext}" 
    elif instance.role == 'staff':
        filename = f"staff_pics/{instance.first_name}_{instance.middle_name}_{instance.last_name}.{ext}"
    else:
        filename = f"others/{instance.first_name}_{instance.middle_name}_{instance.last_name}.{ext}"

    return filename

# ------ SCHOOL TABLE ------
class School(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.IntegerField(unique=True, blank=True, null=True)
    name = models.CharField(max_length=255, unique=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
# function to generate school number
@receiver(pre_save, sender=School)
def set_number(sender, instance, **kwargs):
    if instance.number is None:
        last_instance = sender.objects.order_by('-number').first()
        if last_instance and last_instance.number < 99:
            instance.number = last_instance.number + 1
        else:
            instance.number = 10 
    

# -------- USER TABLE ----------
class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('operator', 'Operator'),
        ('parent', 'Parent'),
        ('student', 'Student'),
        ('staff','Staff')
    ]

    PARENT_TYPE_CHOICES = [
        ('mother', 'Mother'),
        ('father','Father'),
        ('guardian', 'Guardian')
    ]

    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    middle_name = models.CharField(max_length=100, default="")
    school = models.ForeignKey(School, on_delete=models.SET_NULL, null=True, blank=True)
    class_room = models.CharField(max_length=255, null=True, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, default='M')
    parent_type = models.CharField(max_length=10, choices=PARENT_TYPE_CHOICES, default='mother', null=True, blank=True)
    fcm_token = models.CharField(max_length=255, null=True, blank=True)
    profile_picture = models.ImageField(upload_to=user_profile_path, null=True, blank=True)
    mobile_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    sms_opt_out = models.BooleanField(default=False, help_text='If true, do not send SMS (opt-out per Tanzania TCRA rules)')
    balance_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Per-parent default balance threshold that triggers a low-balance reminder for their children. Null falls back to the system default.',
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.role}"
    

# ------ RFID_CARD TABLE ---------
class RFIDCard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    card_number = models.CharField(max_length=50, unique=True)
    uid_hex = models.CharField(max_length=20, unique=True, null=True, blank=True)
    student_or_staff = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        limit_choices_to={'role__in': ['student', 'staff']},
        related_name='rfid_cards',
        help_text='Owner of the card. A student/staff may have multiple cards',
    )
    control_number = models.CharField(max_length=50, unique=True)
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.0,
        validators=[MinValueValidator(RFID_BALANCE_FLOOR)],
    )
    held_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    insufficient_meal_count = models.PositiveIntegerField(default=0)  # Field to track insufficient meals
    is_active = models.BooleanField(default=True)
    issued_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            CheckConstraint(
                check=Q(balance__gte=RFID_BALANCE_FLOOR),
                name='rfidcard_balance_floor_gte_minus500',
            ),
            CheckConstraint(check=Q(held_balance__gte=0), name='rfidcard_held_balance_nonnegative'),
        ]

    def __str__(self):
        return f"Card: {self.card_number} - {self.student_or_staff.first_name}"


# ------ CARD REPLACEMENT LINK TABLE ------
class ReplacementLink(models.Model):
    """Audit row linking an old (lost) card to its replacement.

    The old card is deactivated and a new card is issued for the same
    student/staff. Balance is migrated and transactional history is repointed to
    the new card. This row preserves the old -> new linkage for traceability.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    old_card = models.OneToOneField(RFIDCard, on_delete=models.CASCADE, related_name='replaced_by')
    new_card = models.OneToOneField(RFIDCard, on_delete=models.CASCADE, related_name='replacement_of')
    replaced_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='card_replacements', help_text='Admin who performed the replacement',
    )
    reason = models.TextField(help_text='Reason for replacement (e.g. card lost or damaged)')
    replaced_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Replace {self.old_card.card_number} -> {self.new_card.card_number}"


# ------ BANK_DEPOSIT TABLE
class BankDeposit(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('mobile_money', 'Mobile money'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    control_number = models.ForeignKey(RFIDCard, on_delete=models.CASCADE, to_field='control_number')
    # student_or_ = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'student'})
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cash')
    provider = models.CharField(max_length=50, null=True, blank=True)
    reference = models.CharField(max_length=100, null=True, blank=True)
    transaction_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bank_deposits',
        help_text='Parent who requested the deposit (optional, for audit)'
    )

    def __str__(self):
        return f"Deposit: {self.amount} - {self.control_number}"

    
# ------ PARENT_STUDENT TABLE -------- 
class ParentStudent(models.Model):
    parent = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="children", limit_choices_to={'role': 'parent'})
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="parents", limit_choices_to={'role': 'student'})

    class Meta:
        unique_together = ('parent', 'student')

    def __str__(self):
        return f"Parent: {self.parent.username} - Student: {self.student.username}"


class SpendingRule(models.Model):
    """Optional per-student daily wallet spend cap configured by a parent."""
    student = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name='spending_rule',
        limit_choices_to={'role': 'student'},
    )
    daily_limit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class BlockedItem(models.Model):
    """A canteen item that a student's linked parent has blocked."""
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='blocked_items')
    item = models.ForeignKey('CanteenItem', on_delete=models.PROTECT, related_name='blocked_for_students')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'item'], name='uniq_blocked_item_per_student')]

# ------ CANTEEN ITEM TABLE ---------
class CanteenItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True, help_text='Soft-deactivate instead of deleting when transaction history exists')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class StockLevel(models.Model):
    item = models.OneToOneField(CanteenItem, on_delete=models.PROTECT, related_name='stock_level')
    quantity = models.PositiveIntegerField(default=0)
    low_threshold = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class StockMovement(models.Model):
    item = models.ForeignKey(CanteenItem, on_delete=models.PROTECT, related_name='stock_movements')
    delta = models.IntegerField()
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    source_transaction = models.ForeignKey(
        'Transaction', on_delete=models.PROTECT, null=True, blank=True, related_name='stock_movements',
    )
    created_at = models.DateTimeField(auto_now_add=True)


class DailyMenu(models.Model):
    MEAL_TYPE_CHOICES = [
        ('breakfast', 'Breakfast'), ('lunch', 'Lunch'), ('dinner', 'Dinner'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateField(db_index=True)
    meal_type = models.CharField(max_length=50, choices=MEAL_TYPE_CHOICES)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['date', 'meal_type'], name='uniq_daily_menu_date_meal')]
        ordering = ['date', 'meal_type']

    def __str__(self):
        return f'{self.date} {self.meal_type} menu'


class DailyMenuItem(models.Model):
    menu = models.ForeignKey(DailyMenu, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(CanteenItem, on_delete=models.PROTECT, related_name='daily_menu_entries')
    price_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['menu', 'item'], name='uniq_daily_menu_item')]

    def __str__(self):
        return f'{self.menu}: {self.item}'

# ----- SCAN SESSION TABLE ------
class ScanSession(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    SESSION_TYPE_CHOICES = [
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner','Dinner')
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operator = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'operator'})
    type = models.CharField(max_length=50, choices=SESSION_TYPE_CHOICES, default='breakfast')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    start_at = models.DateTimeField(auto_now_add=True)
    end_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session {self.type} - {self.status}"


# ------ TRANSACTIONS TABLE ------
class Transaction(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('successful', 'Successful'),
        ('failed', 'Failed'),
        ('penalty', 'Penalty')
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_or_staff = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role__in': ['student', 'staff']})
    rfid_card = models.ForeignKey(RFIDCard, on_delete=models.CASCADE)
    item = models.ForeignKey(CanteenItem, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    charged_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    transaction_date = models.DateTimeField(auto_now_add=True)
    transaction_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    session = models.ForeignKey(
        'ScanSession', on_delete=models.SET_NULL, null=True, blank=True, db_index=True,
        help_text='Scan session that produced this transaction (for audit & reversal)'
    )
    is_voided = models.BooleanField(default=False, db_index=True, help_text='Set when a reversal restores the balance')
    SCAN_SOURCE_CHOICES = [('usb', 'USB'), ('nfc', 'NFC'), ('manual', 'Manual')]
    scan_source = models.CharField(max_length=10, choices=SCAN_SOURCE_CHOICES, default='usb')
    preorder_item = models.ForeignKey('PreOrderItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')

    class Meta:
        indexes = [
            models.Index(fields=['transaction_date'], name='txn_date_idx'),
            models.Index(fields=['transaction_status', 'is_voided'], name='txn_status_void_idx'),
        ]

    def __str__(self):
        return f"{self.student_or_staff.username} - {self.item.name} - ${self.amount}"

# ----- NOTIFICATION TABLE ------
class Notification(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    TYPE_CHOICES = [
        ('transaction', 'Transaction'),
        ('system', 'System Update'),
        ('reminder', 'Reminder'),
        ('message', 'Message'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(CustomUser, on_delete=models.CASCADE)  # Allow all users, not just parents
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, null=True, blank=True)  # Optional
    title = models.CharField(max_length=100, null=True, blank=True)
    message = models.TextField()
    dedupe_key = models.CharField(max_length=160, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    retry_count = models.IntegerField(default=0)
    type = models.CharField(max_length=15, choices=TYPE_CHOICES, default='message')  # Type of notification
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['recipient', 'dedupe_key'], condition=Q(dedupe_key__isnull=False), name='uniq_notification_recipient_dedupe')]

    def __str__(self):
        return f"Notification for {self.recipient.first_name}: {self.type} - {self.status}"


# ---- SCANNED DATA TABLE -----
class ScannedData(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ScanSession, on_delete=models.CASCADE)  # Links to active session
    student_or_staff = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role__in': ['student', 'staff']})
    rfid_card = models.ForeignKey(RFIDCard, on_delete=models.CASCADE)
    item = models.ForeignKey(CanteenItem, on_delete=models.CASCADE, null=True, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)
    SCAN_SOURCE_CHOICES = [('usb', 'USB'), ('nfc', 'NFC'), ('manual', 'Manual')]
    scan_source = models.CharField(max_length=10, choices=SCAN_SOURCE_CHOICES, default='usb')
    client_scan_id = models.UUIDField(null=True, blank=True, unique=True)

    def __str__(self):
        return f"{self.student_or_staff.username} scanned at {self.scanned_at}"


class InsightFlag(models.Model):
    """Persisted, resolvable evidence for operational or suspicious events."""
    STATUS_CHOICES = [('open', 'Open'), ('resolved', 'Resolved')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=40, default='impossible_scan')
    reference_type = models.CharField(max_length=40, null=True, blank=True)
    reference_id = models.CharField(max_length=80, null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    resolved_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_insights')
    resolved_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    scan_a = models.ForeignKey(ScannedData, on_delete=models.CASCADE, null=True, blank=True, related_name='insight_flags_a')
    scan_b = models.ForeignKey(ScannedData, on_delete=models.CASCADE, null=True, blank=True, related_name='insight_flags_b')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['kind', 'scan_a', 'scan_b'], name='uniq_insight_scan_pair'),
            models.UniqueConstraint(
                fields=['kind', 'reference_type', 'reference_id'],
                condition=Q(reference_type__isnull=False, reference_id__isnull=False),
                name='uniq_insight_reference',
            ),
        ]


class DailyStats(models.Model):
    date = models.DateField()
    meal_type = models.CharField(max_length=20)
    revenue = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    penalty_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    meals = models.PositiveIntegerField(default=0)
    unique_students = models.PositiveIntegerField(default=0)
    deposits_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    reversals = models.PositiveIntegerField(default=0)
    variance_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        constraints = [models.UniqueConstraint(fields=['date', 'meal_type'], name='uniq_daily_stats_date_meal')]


# ------ LEDGER ENTRY TABLE ------
class LedgerEntry(models.Model):
    EVENT_TYPES = [
        ('purchase', 'Purchase / Penalty'),
        ('deposit', 'Deposit'),
        ('reversal', 'Reversal'),
        ('card_replacement', 'Card Replacement'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rfid_card = models.ForeignKey(RFIDCard, on_delete=models.CASCADE, db_index=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # signed: negative for purchases/penalties, positive for deposits/reversals
    balance_before = models.DecimalField(max_digits=10, decimal_places=2)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    ref_transaction = models.ForeignKey(
        Transaction, on_delete=models.SET_NULL, null=True, blank=True, db_index=True,
        help_text='Transaction reversed/deposited (if any)'
    )
    ref_deposit = models.ForeignKey(
        BankDeposit, on_delete=models.SET_NULL, null=True, blank=True, db_index=True,
        help_text='Bank deposit that credited the balance (if any)'
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['rfid_card', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} {self.rfid_card.card_number} bal:{self.balance_before}→{self.balance_after}"


class LedgerAccount(models.Model):
    ACCOUNT_TYPES = [('asset', 'Asset'), ('liability', 'Liability'), ('equity', 'Equity'), ('income', 'Income'), ('expense', 'Expense')]
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=12, choices=ACCOUNT_TYPES)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} {self.name}'


class JournalEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=40)
    idempotency_key = models.CharField(max_length=200, unique=True)
    ref_transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, null=True, blank=True, related_name='journal_entries')
    ref_deposit = models.ForeignKey(BankDeposit, on_delete=models.PROTECT, null=True, blank=True, related_name='journal_entries')
    ref_reversal = models.ForeignKey('Reversal', on_delete=models.PROTECT, null=True, blank=True, related_name='journal_entries')
    memo = models.TextField(blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=['event_type', 'created_at'])]

    def save(self, *args, **kwargs):
        if self.pk and JournalEntry.objects.filter(pk=self.pk).exists():
            raise ValueError('Journal entries are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Journal entries are append-only.')


class JournalLine(models.Model):
    DIRECTIONS = [('debit', 'Debit'), ('credit', 'Credit')]
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name='lines')
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name='lines')
    rfid_card = models.ForeignKey(RFIDCard, on_delete=models.PROTECT, null=True, blank=True, related_name='journal_lines')
    fund = models.ForeignKey('SponsorFund', on_delete=models.PROTECT, null=True, blank=True, related_name='journal_lines')
    direction = models.CharField(max_length=6, choices=DIRECTIONS)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    balance_after = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['rfid_card', 'created_at']),
            models.Index(fields=['account', 'created_at']),
        ]
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name='journal_line_amount_positive'),
            models.CheckConstraint(check=Q(direction__in=['debit', 'credit']), name='journal_line_direction_valid'),
        ]

    def save(self, *args, **kwargs):
        if self.pk and JournalLine.objects.filter(pk=self.pk).exists():
            raise ValueError('Journal lines are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Journal lines are append-only.')


class LedgerIntegrityRun(models.Model):
    STATUS_CHOICES = [('ok', 'OK'), ('mismatch', 'Mismatch')]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    checked_at = models.DateTimeField(auto_now_add=True)
    global_balanced = models.BooleanField(default=False)
    mismatched_cards = models.JSONField(default=list)
    result = models.JSONField(default=dict)


class PreOrder(models.Model):
    STATUS_CHOICES = [
        ('placed', 'Placed'), ('fulfilled', 'Fulfilled'), ('cancelled', 'Cancelled'),
        ('no_show', 'No show'), ('expired', 'Expired'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='preorders')
    card = models.ForeignKey(RFIDCard, on_delete=models.PROTECT, related_name='preorders')
    date = models.DateField(db_index=True)
    meal_type = models.CharField(max_length=50, choices=ScanSession.SESSION_TYPE_CHOICES)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='placed', db_index=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    cutoff_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_preorders')
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'date', 'meal_type'], condition=Q(status='placed'), name='uniq_active_preorder_student_date_meal')]
        indexes = [models.Index(fields=['date', 'meal_type', 'status'])]


class PreOrderItem(models.Model):
    preorder = models.ForeignKey(PreOrder, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(CanteenItem, on_delete=models.PROTECT, related_name='preorder_items')
    quantity = models.PositiveSmallIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    fulfilled_quantity = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['preorder', 'item'], name='uniq_preorder_item'),
            models.CheckConstraint(check=Q(quantity__gt=0), name='preorder_item_quantity_positive'),
            models.CheckConstraint(check=Q(fulfilled_quantity__lte=F('quantity')), name='preorder_fulfilled_not_over_quantity'),
        ]


class SponsorFund(models.Model):
    STATUS_CHOICES = [('active', 'Active'), ('paused', 'Paused'), ('closed', 'Closed')]
    name = models.CharField(max_length=150, unique=True)
    sponsor_name = models.CharField(max_length=150)
    contact = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    alert_threshold = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_sponsor_funds')
    created_at = models.DateTimeField(auto_now_add=True)


class FundContribution(models.Model):
    METHOD_CHOICES = [('cash', 'Cash'), ('bank', 'Bank'), ('mobile_money', 'Mobile money')]
    fund = models.ForeignKey(SponsorFund, on_delete=models.PROTECT, related_name='contributions')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    reference = models.CharField(max_length=150, blank=True)
    received_at = models.DateTimeField()
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_fund_contributions')
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name='fund_contributions')
    created_at = models.DateTimeField(auto_now_add=True)


class SponsorshipAllocation(models.Model):
    fund = models.ForeignKey(SponsorFund, on_delete=models.PROTECT, related_name='allocations')
    student = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='sponsorship_allocations')
    meal_types = models.JSONField(default=list)
    daily_cap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    per_meal_cap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['fund', 'student'], condition=Q(is_active=True), name='uniq_active_fund_student_allocation',
        )]


class TransactionPayment(models.Model):
    SOURCE_CHOICES = [('wallet', 'Wallet'), ('fund', 'Fund'), ('preorder', 'Pre-order')]
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name='payment_parts')
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    fund = models.ForeignKey(SponsorFund, on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name='transaction_payments')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(
            check=(Q(source='fund', fund__isnull=False) | (~Q(source='fund') & Q(fund__isnull=True))),
            name='txn_payment_fund_source_matches',
        )]


# ------ RECONCILIATION TABLE ------
class Reconciliation(models.Model):
    STATUS_CHOICES = [
        ('matched', 'Matched'),
        ('variance', 'Variance'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField(ScanSession, on_delete=models.CASCADE, unique=True)
    scanned_value = models.DecimalField(max_digits=10, decimal_places=2, help_text='Sum of all ScannedData.item.price for this session')
    expected_cash = models.DecimalField(max_digits=10, decimal_places=2, help_text='Operator-entered till/cash amount')
    variance = models.DecimalField(max_digits=10, decimal_places=2, editable=False, help_text='expected_cash - scanned_value')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='matched')
    reason = models.TextField(blank=True, help_text='Why there is variance (if any)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"Reconciliation {self.session.id}: scanned={self.scanned_value} expected={self.expected_cash} variance={self.variance} {self.status}"


class FeatureFlag(models.Model):
    key = models.CharField(max_length=100, unique=True)
    enabled = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='updated_feature_flags',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key']

    def __str__(self):
        return f"{self.key}: {'enabled' if self.enabled else 'disabled'}"


# ------ PASSWORD RESET TOKEN TABLE ------
class PasswordResetToken(models.Model):
    PURPOSE_CHOICES = [
        ('password_reset', 'Password reset'),
        ('invite', 'Password invite'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token_hash = models.CharField(max_length=128, unique=True)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default='password_reset')
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Reset token for {self.user.username} (used: {self.used_at is not None})"


# ------ REVERSAL TABLE ------
class Reversal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, unique=True)
    reversed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reversals', help_text='Operator/admin who voided the transaction'
    )
    reason = models.TextField(help_text='Reason for reversal')
    ref = models.CharField(max_length=50, blank=True, help_text='Optional reversal reference number')
    reversed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-reversed_at']
        indexes = [
            models.Index(fields=['transaction', 'reversed_at']),
        ]

    def __str__(self):
        return f"Reversal {self.transaction.id} by {self.reversed_by.username if self.reversed_by else '?'} at {self.reversed_at}"


# ------ AUDIT LOG TABLE ------
class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('deactivate', 'Deactivate'),
        ('activate', 'Activate'),
        ('delete', 'Delete'),
        ('approve', 'Approve'),
        ('reverse', 'Reverse'),
        ('replace', 'Replace'),
        ('login', 'Login'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    content_type = models.ForeignKey('contenttypes.ContentType', on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.CharField(max_length=64, null=True, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    path = models.CharField(max_length=512, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['actor', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.timestamp} {self.actor} {self.action} {self.object_repr}"


# ------ SMS DELIVERY LOG ------
class SMSLog(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('skipped_opt_out', 'Skipped - Opt Out'),
        ('skipped_rate_limit', 'Skipped - Rate Limited'),
        ('skipped_no_phone', 'Skipped - No Phone'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sms_logs')
    notification = models.ForeignKey(Notification, on_delete=models.SET_NULL, null=True, blank=True, related_name='sms_logs')
    phone = models.CharField(max_length=20)
    body = models.TextField()
    provider = models.CharField(max_length=30, default='log')
    provider_sid = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error = models.TextField(null=True, blank=True)
    segments = models.PositiveSmallIntegerField(default=1)
    cost_estimate = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'created_at']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"SMS to {self.phone} {self.status} ({self.provider})"
