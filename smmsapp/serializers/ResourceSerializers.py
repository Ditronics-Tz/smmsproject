from rest_framework import serializers
from ..models import CustomUser, RFIDCard, ParentStudent, Transaction, ScanSession, School
from django.db.models import Q

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
        fields = ['id','first_name','middle_name', 'last_name','username','parent_type','gender','email','mobile_number','class_room','school','profile_picture','date_joined']

# ------ RFID Card INFO -----
class RFIDCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = RFIDCard
        fields = ['id','balance', 'is_active','control_number','card_number','issued_date']

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
        fields = ['id','status', 'type', 'created_at', 'updated_at']

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