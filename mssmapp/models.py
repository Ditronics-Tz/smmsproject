from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid
import os

# -------- profile path creation ------
def user_profile_path(instance, filename):
    """Generate file path for profile picture"""
    ext = filename.split('.')[-1]
    filename = f"profile_pics/{instance.id}.{ext}"
    return os.path.join('uploads/', filename)

# -------- USER TABLE ----------
class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('operator', 'Operator'),
        ('parent', 'Parent'),
        ('student', 'Student'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # UUID for better security
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    school_name = models.CharField(max_length=255, null=True, blank=True)
    fcm_token = models.CharField(max_length=255, null=True, blank=True)
    profile_picture = models.ImageField(upload_to=user_profile_path, null=True, blank=True)

    def __str__(self):
        return f"{self.username} - {self.role}"

# ------ RFID_CARD TABLE ---------
class RFIDCard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    card_number = models.CharField(max_length=50, unique=True)
    qrcode_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    student = models.OneToOneField(CustomUser, on_delete=models.CASCADE, limit_choices_to={'customuser__role': 'student'})
    control_number = models.CharField(max_length=50, unique=True)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    is_active = models.BooleanField(default=True)
    issued_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Card: {self.card_number} - {self.student.username}"

# ------ BANK_DEPOSIT TABLE
class BankDeposit(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    control_number = models.ForeignKey(RFIDCard, on_delete=models.CASCADE, to_field='control_number')
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'costomuser__role': 'student'})
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Deposit: {self.amount} - {self.control_number}"

    
# ------ PARENT_STUDENT TABLE -------- 
class ParentStudent(models.Model):
    parent = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="children", limit_choices_to={'customuser__role': 'parent'})
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="parents", limit_choices_to={'customuser__role': 'student'})

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
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'customuser__role': 'student'})
    rfid_card = models.ForeignKey(RFIDCard, on_delete=models.CASCADE)
    item = models.ForeignKey(CanteenItem, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_date = models.DateTimeField(auto_now_add=True)
    transaction_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')

    def __str__(self):
        return f"{self.student.username} - {self.item.name} - ${self.amount}"
    
# ----- NOTIFICATION TABLE ------
class Notification(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'customuser__role': 'parent'})
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for {self.parent.username}: {self.status}"





