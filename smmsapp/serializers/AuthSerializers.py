import json
from uuid import UUID
from rest_framework import serializers
from ..models import CustomUser, School
from django.db.models import Q
from rest_framework import generics, status
from rest_framework.response import Response
import random
import string
from datetime import datetime
from ..models import CustomUser, RFIDCard, Notification, ParentStudent
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
    # fcm_token = serializers.CharField(required=False)

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
    password = serializers.CharField(write_only=True, required=False)  # Optional for students
    middle_name = serializers.CharField(write_only=True, required=False)  # Optional for middle name
    gender = serializers.ChoiceField(choices=CustomUser.GENDER_CHOICES, required=False)  # Gender choices
    profile_picture = serializers.ImageField(write_only=True, required=False)

   # Accept multiple parent IDs when creating a student
    parent_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False)
    
    # Accept multiple student IDs when creating a parent
    student_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False)

    class Meta:
        model = CustomUser
        fields = ['id', 'first_name','middle_name', 'last_name', 'username', 'email', 'mobile_number', 'role', 
                  'school','class_room', 'gender', 'password','profile_picture','parent_type',
                  'parent_ids', 'student_ids']

    # Generate strong password
    def generate_password(self, last_name):
        """Generate a strong random password."""
        digits = string.digits
        special_chars = "!@#$%&*"  # Limit special characters

        password = [
            random.choice(digits),
            random.choice(special_chars)
        ]

        all_chars = digits + special_chars
        password += random.choices(all_chars, k=1)  # Ensure 8-character length
        random.shuffle(password)

        return f'{last_name}{"".join(password)}'

    # Generate unique username for student
    def generate_username(self, first_name, last_name, school_name):
        """Generate a unique username using first_name.last_name + 3 random digits"""
        base_username = f"{first_name.lower()}.{last_name.lower()}.{school_name.lower()}"
        year = datetime.now().year
        username = f"{base_username}{year}"
        if CustomUser.objects.filter(username=username).exists():
            raise serializers.ValidationError({"code": 108, "message": "This user is already exist"})
        return username
    
    # Create user
    def create(self, validated_data):
        role = validated_data.pop('role')
        student_ids = validated_data.pop('student_ids', [])
        parent_ids = validated_data.pop('parent_ids', [])
        user = None 

        if role == 'student':
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

            # If `parent_id` is provided, link parent to student
            for parent_id in parent_ids:
                try:
                    parent = CustomUser.objects.get(id=parent_id, role='parent')
                    ParentStudent.objects.get_or_create(parent=parent, student=user)
                except CustomUser.DoesNotExist:
                    raise serializers.ValidationError({"code": 107, "message": "Invalid parent ID"})
            
        else:
            last_name = validated_data.get('last_name', '').strip()
            password = self.generate_password(last_name)
            validated_data['password'] = password # password

            user = CustomUser.objects.create(role=role, **validated_data)
            user.set_password(password)  # ✅ Hash password
            user.save()

            # If `student_id` is provided, link student to parent
            for student_id in student_ids:
                try:
                    student = CustomUser.objects.get(id=student_id, role='student')
                    ParentStudent.objects.get_or_create(parent=user, student=student)
                except CustomUser.DoesNotExist:
                    raise serializers.ValidationError({"code": 107, "message": "Invalid student ID"})

            title = f"Login Credentials"
            message = f"Hello {user.first_name}, your account was created successfully. Use username {user.username} and password {password}."
            Notification.objects.create(recipient=user,title=title, type='reminder', message=message)
        return user

    # Edit user
    def update(self, instance, validated_data):
        role = validated_data.pop('role')
        student_ids = validated_data.pop('student_ids', [])
        parent_ids = validated_data.pop('parent_ids', [])
        user = None

        if role == 'student':
            user = super().update(instance, validated_data)

            # Clear existing parents first (to avoid duplicates)
            ParentStudent.objects.filter(student=user).delete()

            # If `parent_id` is provided, link parent to student
            for parent_id in parent_ids:
                try:
                    parent = CustomUser.objects.get(id=parent_id, role='parent')
                    ParentStudent.objects.update_or_create(parent=parent, student=user)
                except CustomUser.DoesNotExist:
                    raise serializers.ValidationError({"code": 107, "message": "Invalid parent ID"})
            
        else:
            user = super().update(instance, validated_data)

            # Clear existing students first (to avoid duplicates)
            ParentStudent.objects.filter(parent=user).delete()

            # Add new students
            for student_id in student_ids:
                try:
                    student = CustomUser.objects.get(id=student_id, role='student')
                    ParentStudent.objects.update_or_create(parent=user, student=student)
                except CustomUser.DoesNotExist:
                    raise serializers.ValidationError({"code": 107, "message": "Invalid student ID"})
                
        return user





