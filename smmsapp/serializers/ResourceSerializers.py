from rest_framework import serializers
from ..models import CustomUser, RFIDCard, ParentStudent, Transaction, ScanSession, School, CanteenItem, ScannedData
from django.db.models import Q
from datetime import datetime
import random

# ---- SCHOOL INFO ----
class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = ['id', 'name', 'location']


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


# ------ PARENT INFO -----
class ParentSerializer(serializers.ModelSerializer):
    # school = SchoolSerializer(read_only = True)
    class Meta: 
        model = CustomUser
        fields = ['id', 'first_name', 'last_name','parent_type', 'email', 'mobile_number', 'gender']


# ----- TRANSACTION INFO ------
class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model =  Transaction
        fields = ['id','amount','transaction_date','transaction_status']


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
    # transactions = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name',  'last_name','gender', 'class_room',
                  'school', 'school_id','profile_picture', 'rfid_card', 'parents']

    def get_parents(self, obj):
        parents = ParentStudent.objects.filter(student=obj).select_related('parent')
        return ParentSerializer([parent.parent for parent in parents], many = True).data
        
        # def get_transactions(self, obj):
        #     transactions = Transaction.objects.filter(student=obj)
        #     return TransactionSerializer(transactions, many=True).data


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
    class Meta:
        model = RFIDCard
        fields = ['id', 'balance', 'student', 'is_active', 'control_number', 'card_number', 'issued_date']
        read_only_fields = ['control_number']  # Ensure control_number isn't required in requests

    # Generate control number automatically
    def generate_control_number(self):
        # Generate control number in the format STU{year}{month}{random6digit}
        year = datetime.now().year
        month = f"{datetime.now().month:02d}"  # Ensure month is always two digits (e.g., 01, 02)
        random6digit = random.randint(100000, 999999)
        return f"STU{year}{month}{random6digit}"

    # Create a new RFID card
    def create(self, validated_data):
        control_number = self.generate_control_number()
        validated_data['control_number'] = control_number
        return RFIDCard.objects.create(is_active=False, **validated_data)

     # Update RFID Card (Prevents control_number changes)
    def update(self, instance, validated_data):
        
        validated_data.pop('control_number', None)  # Ignore control_number if provided
        return super().update(instance, validated_data)