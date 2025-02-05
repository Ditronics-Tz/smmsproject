from rest_framework import serializers
from ..models import CustomUser
from django.db.models import Q
import random
import string
from datetime import datetime
from ..models import CustomUser, RFIDCard

# ----- USER SERIALIZER-----
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'mobile_number', 'role', 'profile_picture', 'first_name', 'last_name', 'is_superuser']

#  ----- LOGIN SERIALIZER ----- 
class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        username = data.get('username')
        password = data.get('password')

        user = CustomUser.objects.filter(
            Q(username=username) | Q(mobile_number=username)
        ).first()

        if user and user.check_password(password):
            data['user'] = user
        # else:
        #     raise serializers.ValidationError("Invalid credentials")

        return data

#  ----- USER CREATE SERIALIAZER ----
class UserCreateSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(choices=CustomUser.ROLE_CHOICES)  # Allow role selection
    control_number = serializers.CharField(write_only=True, required=False)  # Only needed for students
    password = serializers.CharField(write_only=True, required=False)  # Optional for students
    middle_name = serializers.CharField(write_only=True, required=False)  # Optional for middle name
    gender = serializers.ChoiceField(choices=CustomUser.GENDER_CHOICES, required=False)  # Gender choices
    profile_picture = serializers.ImageField(write_only=True, required=False)
    card_number = serializers.CharField(write_only=True, required=False) # Only needed for student 

    class Meta:
        model = CustomUser
        fields = ['id', 'first_name','middle_name', 'last_name', 'email', 'mobile_number', 'role', 
                  'school_name','class_room', 'gender', 'password', 'control_number','profile_picture','card_number']

    # Generate control number automatic
    def generate_control_number(self):
        # Generate control number in the format STU{year}{random6digit}
        year = datetime.now().year
        month = datetime.now().month
        random6digit = random.randint(100000, 999999)
        return f"STU{year}{month}{random6digit}"

    # Generate unique username for student
    def generate_username(self, first_name, last_name, school_name):
        """Generate a unique username using first_name.last_name + 3 random digits"""
        base_username = f"{first_name.lower()}.{last_name.lower()}.{school_name.lower()}"
        year = datetime.now().year
        return f"{base_username}{year}"
    
    # # Validate card number
    def validate_card_number(self, value):
        if RFIDCard.objects.filter(card_number = value).exists():
            raise serializers.ValidationError("This card already exist")
        return value
    
    # Create user
    def create(self, validated_data):
        role = validated_data.pop('role')
        user = None 

        if role == 'student':
            card_number = validated_data.pop('card_number','')
            # Generate username from first name and last name
            first_name = validated_data.get('first_name', '').strip()
            last_name = validated_data.get('last_name', '').strip()
            school_name = validated_data.get('school_name','').strip()

            if not first_name or not last_name:
                raise serializers.ValidationError({"error": "First name and last name are required for students."})

            username = self.generate_username(first_name, last_name, school_name)

            validated_data.pop('password', None) # Students do not need a password
            validated_data['username'] = username

            user = CustomUser.objects.create(role=role, **validated_data)
            
            
            control_number = self.generate_control_number()
            RFIDCard.objects.create(student=user, control_number=control_number, card_number=card_number, balance=0.0, is_active=False)
        else:
            # Non-student users must have a password
            password = validated_data.pop('password', None)
            if not password:
                raise serializers.ValidationError({"password": "Password is required for non-student users"})

            # Generate username from email if not provided
            validated_data['username'] = validated_data.get('email', f"user{random.randint(1000, 9999)}")

            user = CustomUser.objects.create(role=role, **validated_data)
            user.set_password(password)  # ✅ Hash password
            user.save()
        return user


