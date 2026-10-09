from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer


# ---- SHARED REQUEST BODIES FOR THE APIView ENDPOINTS ----
class SearchRequestSerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, default='')


class UserListRequestSerializer(SearchRequestSerializer):
    role = serializers.CharField(required=False, allow_blank=True)


class StudentIdRequestSerializer(serializers.Serializer):
    student_id = serializers.UUIDField(required=False, allow_null=True)


class ParentIdRequestSerializer(serializers.Serializer):
    parent_id = serializers.UUIDField(required=False, allow_null=True)


class StaffIdRequestSerializer(serializers.Serializer):
    staff_id = serializers.UUIDField(required=False, allow_null=True)


class OperatorIdRequestSerializer(serializers.Serializer):
    operator_id = serializers.UUIDField(required=False, allow_null=True)


class ItemIdRequestSerializer(serializers.Serializer):
    item_id = serializers.UUIDField(required=False, allow_null=True)


class CardIdRequestSerializer(serializers.Serializer):
    card_id = serializers.UUIDField(required=False, allow_null=True)


class CardActivateDeactivateSerializer(serializers.Serializer):
    card_id = serializers.UUIDField(required=False, allow_null=True)
    action = serializers.ChoiceField(choices=['activate', 'deactivate'], required=False)


class UserActivateDeactivateSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(required=False, allow_null=True)
    action = serializers.ChoiceField(choices=['activate', 'deactivate'], required=False)


class SchoolIdRequestSerializer(serializers.Serializer):
    school_id = serializers.UUIDField(required=False, allow_null=True)


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False, allow_blank=True)


class ChangePasswordRequestSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=False, allow_blank=True)
    new_password = serializers.CharField(required=False, allow_blank=True)
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
    password_set = serializers.BooleanField(source='has_usable_password', read_only=True)
    class Meta: 
        model = CustomUser
        fields = ['id','first_name','middle_name','is_active','role', 'last_name','username','parent_type','gender','email','mobile_number','class_room','school','profile_picture','date_joined','password_set']


# ------ STUDENT INFO ----
class StudentSerializer(serializers.ModelSerializer):
    school = serializers.CharField(source='school.name',read_only=True)
    class Meta: 
        model = CustomUser
        fields = ['id', 'first_name','middle_name', 'last_name', 'gender', 'class_room', 'school', 'profile_picture']
        
        
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
    payment_breakdown = serializers.SerializerMethodField()
    class Meta:
        model =  Transaction
        fields = ['id','amount','charged_amount','student_name', 'card_number','item_name','transaction_date','transaction_status','scan_source','payment_breakdown']

    def get_student_name(self, obj) -> str:
        return f'{obj.student_or_staff.first_name} {obj.student_or_staff.last_name}'

    def get_payment_breakdown(self, obj) -> list[dict]:
        return [{
            'source': row.source,
            'fund_name': row.fund.name if row.fund_id else None,
            'amount': str(row.amount),
        } for row in obj.payment_parts.select_related('fund').all()]


# ---- SESSION INFO -----
@extend_schema_serializer(component_name='OperatorSessionSummary')
class ScanSessionSerializer(serializers.ModelSerializer):
    """Compact session summary embedded in operator detail responses.

    Distinct from the session API's ScanSessionSerializer (which includes the
    operator), so it carries its own component name to avoid a name collision
    that would serve the wrong shape to one of the two endpoints.
    """

    class Meta:
        model = ScanSession
        fields = ['id','status', 'type', 'start_at','end_at', 'updated_at']


# ------ RFID Card INFO -----
class RFIDCardSerializer(serializers.ModelSerializer):
    student_or_staff = UserSerializer(read_only=True)
    class Meta:
        model = RFIDCard
        fields = ['id','balance', 'is_active','control_number','card_number','uid_hex','issued_date','student_or_staff', 'created_at']


# ----- ITEM INFO ----
class CanteenItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CanteenItem
        fields = '__all__'


# ----- FULL STUDENT DETAILS -----
class FullStudentSerializer(serializers.ModelSerializer):
    rfid_card = serializers.SerializerMethodField()
    school = serializers.CharField(source='school.name',read_only=True)
    school_id = serializers.CharField(source='school.id', read_only=True)
    parents = serializers.SerializerMethodField()
    transactions = serializers.SerializerMethodField()
    password_set = serializers.BooleanField(source='has_usable_password', read_only=True)
    sponsorships = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name',  'last_name','gender', 'class_room',
                  'school', 'school_id','profile_picture','transactions', 'rfid_card', 'parents', 'password_set', 'sponsorships']

    @extend_schema_field(RFIDCardSerializer(allow_null=True))
    def get_rfid_card(self, obj):
        card = obj.rfid_cards.filter(is_active=True).first()
        return RFIDCardSerializer(card).data if card else None

    @extend_schema_field(ParentSerializer(many=True))
    def get_parents(self, obj):
        parents = ParentStudent.objects.filter(student=obj).select_related('parent')
        return ParentSerializer([parent.parent for parent in parents], many = True).data
        
    @extend_schema_field(TransactionSerializer(many=True))
    def get_transactions(self, obj):
        transactions = Transaction.objects.filter(student_or_staff=obj).prefetch_related('payment_parts__fund').order_by('-transaction_date')[:10]
        return TransactionSerializer(transactions, many=True).data

    def get_sponsorships(self, obj) -> list[dict]:
        from django.utils import timezone
        from smmsapp.models import SponsorshipAllocation
        today = timezone.localdate()
        allocations = SponsorshipAllocation.objects.filter(
            student=obj, is_active=True, fund__status='active', valid_from__lte=today,
        ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today)).select_related('fund').order_by('priority')
        return [{
            'fund_name': row.fund.name,
            'meal_types': row.meal_types,
            'daily_cap': row.daily_cap,
            'valid_to': row.valid_to,
        } for row in allocations]


# ----- FULL STAFF DETAILS -----
class FullStaffSerializer(serializers.ModelSerializer):
    rfid_card = serializers.SerializerMethodField()
    school = serializers.CharField(source='school.name',read_only=True)
    school_id = serializers.CharField(source='school.id', read_only=True)
    transactions = serializers.SerializerMethodField()
    password_set = serializers.BooleanField(source='has_usable_password', read_only=True)

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name', 'last_name','gender', 'email', 'username', 'mobile_number',
                  'school', 'school_id','profile_picture', 'rfid_card', 'transactions', 'password_set']
        
    @extend_schema_field(RFIDCardSerializer(allow_null=True))
    def get_rfid_card(self, obj):
        card = obj.rfid_cards.filter(is_active=True).first()
        return RFIDCardSerializer(card).data if card else None

    @extend_schema_field(TransactionSerializer(many=True))
    def get_transactions(self, obj):
        transactions = Transaction.objects.filter(student_or_staff=obj).order_by('-transaction_date')[:10]
        return TransactionSerializer(transactions, many=True).data
    

# ----- FULL PARENT DETAILS ----
class FullParentSerializer(serializers.ModelSerializer):
    students = serializers.SerializerMethodField()
    school = serializers.CharField(source='school.name',read_only=True)
    password_set = serializers.BooleanField(source='has_usable_password', read_only=True)

    class Meta:
        model = CustomUser
        fields = ['id','first_name', 'username','middle_name',  'last_name', 'parent_type','email', 'mobile_number','gender',
                  'school', 'students', 'password_set']
        
    @extend_schema_field(StudentSerializer(many=True))
    def get_students(self, obj):
        students = ParentStudent.objects.filter(parent=obj).select_related('student')
        return StudentSerializer([student.student for student in students],many=True).data
    

# ----- FULL OPERATOR DETAILS ----
class FullOperatorSerializer(serializers.ModelSerializer):
    sessions = serializers.SerializerMethodField()
    school = serializers.CharField(source='school.name',read_only=True)
    school_id = serializers.CharField(source='school.id', read_only=True)
    password_set = serializers.BooleanField(source='has_usable_password', read_only=True)

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name', 'last_name','username','email', 'mobile_number','gender',
                  'school', 'sessions','school_id', 'password_set']
        
    @extend_schema_field(ScanSessionSerializer(many=True))
    def get_sessions(self, obj):
        sessions = ScanSession.objects.filter(operator=obj).select_related('operator')
        return ScanSessionSerializer([session for session in sessions],many=True).data
    
# ----- FULL ADMIN DETAILS ------
class FullAdminSerializer(serializers.ModelSerializer):
    school = serializers.CharField(source='school.name', read_only=True)
    school_id = serializers.CharField(source='school.id', read_only=True)
    password_set = serializers.BooleanField(source='has_usable_password', read_only=True)

    class Meta:
        model = CustomUser
        fields = ['id','first_name','middle_name',  'last_name','username','email', 'mobile_number','gender',
                  'school','school_id','password_set']


# ----- CREATE RFID CARD -----
class CreateRFIDCardSerializer(serializers.ModelSerializer):
    card_number = serializers.CharField(required=False, allow_blank=True)
    card_uid = serializers.CharField(required=False, allow_blank=True, write_only=True)
    class Meta:
        model = RFIDCard
        fields = ['id', 'balance', 'student_or_staff', 'is_active', 'control_number', 'card_number', 'card_uid', 'issued_date']
        read_only_fields = ['control_number']  # Ensure control_number isn't required in requests

    # Generate control number automatically
    def generate_control_number(self, school_number):
        # Generate control number in the format STU{year}{month}{random6digit}
        year = datetime.now().year % 100 # get a last two digits
        month = f"{datetime.now().month:02d}"  # Ensure month is always two digits (e.g., 01, 02)
        date = f"{datetime.now().day:02d}"
        random4digit = random.randint(1000, 9999)
        return f"{school_number}{year}{month}{random4digit}"

    # Ensure a card can never be created with a balance below the enforced floor.
    def validate_balance(self, value):
        if value is not None and value < RFID_BALANCE_FLOOR:
            raise serializers.ValidationError(
                f"Balance cannot be below {RFID_BALANCE_FLOOR}."
            )
        return value

    # Create a new RFID card
    def create(self, validated_data):
        from ..services.cards import normalize_uid
        raw_uid = validated_data.pop('card_uid', None)
        if raw_uid:
            try:
                uid_hex = normalize_uid(raw_uid)
            except ValueError as exc:
                raise serializers.ValidationError({'card_uid': str(exc)})
            if RFIDCard.objects.filter(uid_hex=uid_hex).exists():
                raise serializers.ValidationError({'card_uid': 'This UID is already registered.'})
            validated_data['uid_hex'] = uid_hex
        elif not validated_data.get('card_number'):
            raise serializers.ValidationError({'card_number': 'card_number or card_uid is required'})
        student_or_staff = validated_data.get('student_or_staff')

        # Ensure the student_or_staff has a school assigned
        if student_or_staff and student_or_staff.school:
            school_number = student_or_staff.school.number  # Get the school number
        else:
            raise serializers.ValidationError({"school_number": "Student or staff must belong to a school."})

        # The legacy card-number path remains unchanged. UID-only cards get a
        # generated human/USB identifier from the existing number generator.
        if not validated_data.get('card_number'):
            for _ in range(20):
                candidate = f"CARD-{self.generate_control_number(school_number)}"
                if not RFIDCard.objects.filter(card_number=candidate).exists() and not RFIDCard.objects.filter(uid_hex=candidate).exists():
                    validated_data['card_number'] = candidate
                    break
            else:
                raise serializers.ValidationError({'card_uid': 'Could not allocate a unique card number.'})
        if RFIDCard.objects.filter(uid_hex=validated_data.get('card_number').strip().upper()).exists():
            raise serializers.ValidationError({'card_number': 'CARD_UID_CONFLICT'})

        # school_number = validated_data.pop('school_number')
        control_number = self.generate_control_number(school_number)
        validated_data['control_number'] = control_number
        # A newly issued card is always inactive until the student activates it.
        # Assign via the dict (not a duplicate kwarg) so `is_active` supplied in
        # the request cannot collide with the enforced default.
        validated_data['is_active'] = False
        rfid = RFIDCard.objects.create(**validated_data)

        if rfid.student_or_staff.role == 'student':
            # Notify parent
            parents = ParentStudent.objects.filter(student=rfid.student_or_staff)
            for parent_entry in parents:
                Notification.objects.create(
                    title=f"{rfid.student_or_staff.first_name}'s Card Creation",
                    recipient=parent_entry.parent,
                    message=f"Your {rfid.student_or_staff.first_name} {rfid.student_or_staff.last_name}'s meal card is created. \nCard Number: {rfid.card_number}, \nControl Number: {rfid.control_number}, \nBalance: Tsh. {rfid.balance}.",
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
    

# ----- REPLACE CARD SERIALIZER -----
class ReplaceCardSerializer(serializers.Serializer):
    old_card_id = serializers.UUIDField()
    new_card_number = serializers.CharField(trim_whitespace=True, required=False, allow_blank=True)
    card_uid = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(allow_blank=True, default='')
    carry_balance = serializers.BooleanField(default=True)

    def validate(self, attrs):
        if not attrs.get('new_card_number') and not attrs.get('card_uid'):
            raise serializers.ValidationError('new_card_number or card_uid is required')
        return attrs


# ----- SERIALIZER FOR NOTIFICATIONS ------
class NotificationSerializer(serializers.ModelSerializer):
    recipient = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()
    class Meta:
        model = Notification
        fields = ['id', 'message', 'status', 'title', 'type', 'created_at', 'recipient']

    def get_recipient(self, obj) -> str:
        return f'{obj.recipient.first_name} {obj.recipient.last_name}'

    def get_message(self, obj) -> str:
        # Defense-in-depth: never surface a password payload through the API.
        # New rows no longer store plaintext passwords, and a data migration
        # scrubbed historical ones; this guards against any residual leak.
        msg = obj.message
        if obj.type == 'reminder' and any(word in msg.lower() for word in ('password', 'credential')):
            return "Your credentials were sent to your registered email."
        return msg


