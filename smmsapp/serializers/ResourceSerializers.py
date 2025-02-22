from rest_framework import serializers
from ..models import *
from django.db.models import Q
from datetime import datetime
import random

# ---- SCHOOL INFO ----
class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = ['id', 'name', 'location', 'number']


# ----- USER INFO ----
class UserSerializer(serializers.ModelSerializer):
    school = serializers.CharField(source='school.name',read_only=True)
    class Meta: 
        model = CustomUser
        fields = ['id','first_name','middle_name','is_active', 'last_name','username','parent_type','gender','email','mobile_number','class_room','school','profile_picture','date_joined']


# ------ STUDENT INFO ----
class StudentSerializer(serializers.ModelSerializer):
    school = serializers.CharField(source='school.name',read_only=True)
    class Meta: 
        model = CustomUser
        fields = ['id', 'first_name','middle_name', 'last_name', 'gender', 'class_room', 'school']
        
        
# ------ STAFF INFO ----
class StaffSerializer(serializers.ModelSerializer):
    school = serializers.CharField(source='school.name',read_only=True)
    class Meta: 
        model = CustomUser
        fields = ['id', 'first_name','middle_name', 'last_name', 'gender', 'school']


# ------ PARENT INFO -----
class ParentSerializer(serializers.ModelSerializer):
    # school = SchoolSerializer(read_only = True)
    class Meta: 
        model = CustomUser
        fields = ['id', 'first_name', 'last_name','parent_type', 'email', 'mobile_number', 'gender']


# ----- TRANSACTION INFO ------
class TransactionSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    card_number = serializers.CharField(source='rfid_card.card_number', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)
    class Meta:
        model =  Transaction
        fields = ['id','amount','student_name', 'card_number','item','transaction_date','transaction_status']

    def get_student_name(self, obj):
        return f'{obj.student_or_staff.first_name} {obj.student_or_staff.last_name}'


# ---- SESSION INFO -----
class ScanSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScanSession
        fields = ['id','status', 'type', 'start_at','end_at' 'updated_at']


# ------ RFID Card INFO -----
class RFIDCardSerializer(serializers.ModelSerializer):
    student = StudentSerializer(read_only=True)
    class Meta:
        model = RFIDCard
        fields = ['id','balance', 'is_active','control_number','card_number','issued_date','student', 'created_at']


# ----- ITEM INFO ----
class CanteenItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CanteenItem
        fields = '__all__'


# ----- FULL STUDENT DETAILS -----
class FullStudentSerializer(serializers.ModelSerializer):
    rfid_card = RFIDCardSerializer(source = 'rfidcard', read_only = True)
    school = serializers.CharField(source='school.name',read_only=True)
    school_id = serializers.CharField(source='school.id', read_only=True)
    parents = serializers.SerializerMethodField()
    transactions = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name',  'last_name','gender', 'class_room',
                  'school', 'school_id','profile_picture', 'rfid_card', 'parents']

    def get_parents(self, obj):
        parents = ParentStudent.objects.filter(student=obj).select_related('parent')
        return ParentSerializer([parent.parent for parent in parents], many = True).data
        
    def get_transactions(self, obj):
        transactions = Transaction.objects.filter(student_or_teacher=obj).order_by('-transaction_date')[:10]
        return TransactionSerializer(transactions, many=True).data


# ----- FULL STAFF DETAILS -----
class FullStaffSerializer(serializers.ModelSerializer):
    rfid_card = RFIDCardSerializer(source = 'rfidcard', read_only = True)
    school = serializers.CharField(source='school.name',read_only=True)
    school_id = serializers.CharField(source='school.id', read_only=True)
    transactions = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name',  'last_name','gender',
                  'school', 'school_id','profile_picture', 'rfid_card']
        
    def get_transactions(self, obj):
        transactions = Transaction.objects.filter(student_or_staff=obj).order_by('-transaction_date')[:10]
        return TransactionSerializer(transactions, many=True).data
    

# ----- FULL PARENT DETAILS ----
class FullParentSerializer(serializers.ModelSerializer):
    students = serializers.SerializerMethodField()
    school = serializers.CharField(source='school.name',read_only=True)

    class Meta:
        model = CustomUser
        fields = ['id','first_name', 'username','middle_name',  'last_name', 'parent_type','email', 'mobile_number','gender',
                  'school', 'students']
        
    def get_students(self, obj):
        students = ParentStudent.objects.filter(parent=obj).select_related('student')
        return StudentSerializer([student.student for student in students],many=True).data
    

# ----- FULL OPERATOR DETAILS ----
class FullOperatorSerializer(serializers.ModelSerializer):
    sessions = serializers.SerializerMethodField()
    school = serializers.CharField(source='school.name',read_only=True)
    school_id = serializers.CharField(source='school.id', read_only=True)

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name', 'last_name','username','email', 'mobile_number','gender',
                  'school', 'sessions','school_id']
        
    def get_sessions(self, obj):
        sessions = ScanSession.objects.filter(operator=obj).select_related('operator')
        return ScanSessionSerializer([session.session for session in sessions],many=True).data
    

# ----- FULL ADMIN DETAILS ------
class FullAdminSerializer(serializers.ModelSerializer):
    school = serializers.CharField(source='school.name', read_only=True)
    school_id = serializers.CharField(source='school.id', read_only=True)

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name',  'last_name','username','email', 'mobile_number','gender',
                  'school','school_id']


# ----- CREATE RFID CARD -----
class CreateRFIDCardSerializer(serializers.ModelSerializer):
    school_number = serializers.IntegerField()
    class Meta:
        model = RFIDCard
        fields = ['id', 'balance', 'student_or_staff', 'is_active','school_number', 'control_number', 'card_number', 'issued_date']
        read_only_fields = ['control_number']  # Ensure control_number isn't required in requests

    # Generate control number automatically
    def generate_control_number(self, school_number):
        # Generate control number in the format STU{year}{month}{random6digit}
        year = datetime.now().year % 100 # get a last two digits
        month = f"{datetime.now().month:02d}"  # Ensure month is always two digits (e.g., 01, 02)
        date = f"{datetime.now().day:02d}"
        random4digit = random.randint(1000, 9999)
        return f"{school_number}{year}{month}{random4digit}"

    # Create a new RFID card
    def create(self, validated_data):
        school_number = validated_data.pop('school_number')
        control_number = self.generate_control_number(school_number)
        validated_data['control_number'] = control_number
        rfid = RFIDCard.objects.create(is_active=False, **validated_data)

        if rfid.student_or_staff.role == 'student':
            # Notify parent
            parents = ParentStudent.objects.filter(student=rfid.student_or_staff)
            for parent_entry in parents:
                Notification.objects.create(
                    title=f"{rfid.student_or_staff.first_name}'s Card Creation",
                    recipient=parent_entry.parent,
                    message=f"Your {rfid.student.first_name} {rfid.student.last_name}'s meal card is created. \nCard Number: {rfid.card_number}, \nControl Number: {rfid.control_number}, \nBalance: Tsh. {rfid.balance}.",
                    status='pending',
                    type='reminder'
                )
        else: 
            # Notify staff
            Notification.objects.create(
                title=f"Meal Card Creation",
                recipient=rfid.student_or_staff,
                message=f"Your meal card is created. \nCard Number: {rfid.card_number}, \nControl Number: {rfid.control_number}, \nBalance: Tsh. {rfid.balance}.",
                status='pending',
                type='reminder'
            )
        
        return rfid

     # Update RFID Card (Prevents control_number changes)
    def update(self, instance, validated_data):
        
        validated_data.pop('control_number', None)  # Ignore control_number if provided
        return super().update(instance, validated_data)
    

# ----- SERIALIZER FOR NOTIFICATIONS ------
class NotificationSerializer(serializers.ModelSerializer):
    recipient = serializers.SerializerMethodField()
    class Meta:
        model = Notification
        fields = ['id', 'message', 'status', 'title', 'type', 'created_at', 'recipient']

    def get_recipient(self,obj):
        return f'{obj.recipient.first_name} {obj.recipient.last_name}'


