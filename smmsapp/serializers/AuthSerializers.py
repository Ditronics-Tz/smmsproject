from rest_framework import serializers
from ..models import CustomUser, School
from django.db.models import Q
from rest_framework import generics, status
from rest_framework.response import Response
import random
import string
from datetime import datetime
from ..models import CustomUser, RFIDCard, Notification
from .ResourceSerializers import SchoolSerializer

# ----- USER SERIALIZER-----
class AuthUserSerializer(serializers.ModelSerializer):
    school = SchoolSerializer()
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'mobile_number', 'role', 'profile_picture', 'first_name', 'last_name', 'is_superuser', 'school']

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
    username = serializers.CharField(write_only=True, required=False)
    role = serializers.ChoiceField(choices=CustomUser.ROLE_CHOICES)  # Allow role selection
    # control_number = serializers.CharField(write_only=True, required=False)  # Only needed for students
    password = serializers.CharField(write_only=True, required=False)  # Optional for students
    middle_name = serializers.CharField(write_only=True, required=False)  # Optional for middle name
    gender = serializers.ChoiceField(choices=CustomUser.GENDER_CHOICES, required=False)  # Gender choices
    profile_picture = serializers.ImageField(write_only=True, required=False)
    # card_number = serializers.CharField(write_only=True, required=False) # Only needed for student 

    class Meta:
        model = CustomUser
        fields = ['id', 'first_name','middle_name', 'last_name', 'username', 'email', 'mobile_number', 'role', 
                  'school','class_room', 'gender', 'password','profile_picture']

    # Generate control number automatic
    # def generate_control_number(self):
    #     # Generate control number in the format STU{year}{random6digit}
    #     year = datetime.now().year
    #     month = datetime.now().month
    #     random6digit = random.randint(100000, 999999)
    #     return f"STU{year}{month}{random6digit}"

    # Generate strong password
    def generate_password(self):
        """Generate a strong random password."""
        uppercase = string.ascii_uppercase
        lowercase = string.ascii_lowercase
        digits = string.digits
        special_chars = "!@#$%&*"  # Limit special characters

        password = [
            random.choice(uppercase),
            random.choice(lowercase),
            random.choice(digits),
            random.choice(special_chars)
        ]

        all_chars = uppercase + lowercase + digits + special_chars
        password += random.choices(all_chars, k=4)  # Ensure 8-character length
        random.shuffle(password)

        return "".join(password)

    # Generate unique username for student
    def generate_username(self, first_name, last_name, school_name):
        """Generate a unique username using first_name.last_name + 3 random digits"""
        base_username = f"{first_name.lower()}.{last_name.lower()}.{school_name.lower()}"
        year = datetime.now().year
        username = f"{base_username}{year}"
        if CustomUser.objects.filter(username=username).exists():
            raise serializers.ValidationError({"code": 108, "message": "This user is already exist"})
        return username
    
    # # Validate card number
    # def validate_card_number(self, value):
    #     if RFIDCard.objects.filter(card_number = value).exists():
    #         raise serializers.ValidationError({"code": 105, "message": "This card already exist"})
    #     return value
    
    # Create user
    def create(self, validated_data):
        role = validated_data.pop('role')
        user = None 

        if role == 'student':
            # card_number = validated_data.pop('card_number','')
            
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
            user.save()
            
            # control_number = self.generate_control_number()
            # RFIDCard.objects.create(student=user, control_number=control_number, card_number=card_number, balance=0.0, is_active=False)
        else:
            password = self.generate_password()
            validated_data['password'] = password # password

            user = CustomUser.objects.create(role=role, **validated_data)
            user.set_password(password)  # ✅ Hash password
            user.save()

            message = f"Hello {user.first_name}, your account was created successfully. Use username {user.username} and password {password}."
            Notification.objects.create(recipient=user, type='reminder', message=message)
        return user


