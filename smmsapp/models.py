from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, CheckConstraint
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
RFID_BALANCE_FLOOR = Decimal('-500.00')

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

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.role}"
    

# ------ RFID_CARD TABLE ---------
class RFIDCard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    card_number = models.CharField(max_length=50, unique=True)
    student_or_staff = models.OneToOneField(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role__in': ['student', 'staff']})
    control_number = models.CharField(max_length=50, unique=True)
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.0,
        validators=[MinValueValidator(RFID_BALANCE_FLOOR)],
    )
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
        ]

    def __str__(self):
        return f"Card: {self.card_number} - {self.student_or_staff.first_name}"


# ------ BANK_DEPOSIT TABLE
class BankDeposit(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    control_number = models.ForeignKey(RFIDCard, on_delete=models.CASCADE, to_field='control_number')
    # student_or_ = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'student'})
    amount = models.DecimalField(max_digits=10, decimal_places=2)
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

# ------ CANTEEN ITEM TABLE ---------
class CanteenItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

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
    transaction_date = models.DateTimeField(auto_now_add=True)
    transaction_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    session = models.ForeignKey(
        ScanSession, on_delete=models.SET_NULL, null=True, blank=True, db_index=True,
        help_text='Scan session that produced this transaction (for audit & reversal)'
    )
    is_voided = models.BooleanField(default=False, db_index=True, help_text='Set when a reversal restores the balance')

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
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    retry_count = models.IntegerField(default=0)
    type = models.CharField(max_length=15, choices=TYPE_CHOICES, default='message')  # Type of notification
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for {self.recipient.first_name}: {self.type} - {self.status}"


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

# ---- SCANNED DATA TABLE -----
class ScannedData(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ScanSession, on_delete=models.CASCADE)  # Links to active session
    student_or_staff = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role__in': ['student', 'staff']})
    rfid_card = models.ForeignKey(RFIDCard, on_delete=models.CASCADE)
    item = models.ForeignKey(CanteenItem, on_delete=models.CASCADE, null=True, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student_or_staff.username} scanned at {self.scanned_at}"


# ------ LEDGER ENTRY TABLE ------
class LedgerEntry(models.Model):
    EVENT_TYPES = [
        ('purchase', 'Purchase / Penalty'),
        ('deposit', 'Deposit'),
        ('reversal', 'Reversal'),
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
