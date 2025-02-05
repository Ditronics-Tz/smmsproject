from rest_framework import serializers
from ..models import CustomUser, RFIDCard, ParentStudent, Transaction
from django.db.models import Q

# ----- STUDENT INFO ----
class StudentSerializer(serializers.ModelSerializer):
    class Meta: 
        model = CustomUser
        fields = ['id','first_name','middle_name', 'last_name','gender','class_room','school_name','profile_picture','date_joined']

# ------ RFID Card INFO -----
class RFIDCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = RFIDCard
        fields = ['id','balance', 'is_active','control_number','card_number','issued_date']

# ------ PARENT INFO -----
class ParentSerializer(serializers.ModelSerializer):
    class Meta: 
        model = CustomUser
        fields = ['id', 'first_name', 'last_name', 'email', 'mobile_number']

# ----- TRANSACTION INFO ------
class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model =  Transaction
        fields = ['id','amount','transaction_date','transaction_status']

# ----- FULL STUDENT DETAILS -----
class FullStudentSerializer(serializers.ModelSerializer):
    rfid_card = RFIDCardSerializer(source = 'rfidcard', read_only = True)
    parents = serializers.SerializerMethodField()
    # transactions = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name',  'last_name','gender', 'class_room',
                  'school_name','profile_picture', 'rfid_card', 'parents']

    def get_parents(self, obj):
            parents = ParentStudent.objects.filter(student=obj).select_related('parent')
            return ParentSerializer([parent.parent for parent in parents], many = True).data
        
        # def get_transactions(self, obj):
        #     transactions = Transaction.objects.filter(student=obj)
        #     return TransactionSerializer(transactions, many=True).data
