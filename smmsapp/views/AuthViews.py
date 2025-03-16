from django.contrib.auth import authenticate
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.db.models import Q
import random
import string
from ..serializers.AuthSerializers import UserCreateSerializer, AuthUserSerializer, LoginSerializer
from ..models import CustomUser as User, RFIDCard, Notification
from ..permissions.CustomPermissions import IsAdminOnly, IsAdminOrParent

# Generate JWT tokens for user
def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'token': str(refresh.access_token),
    }


# User Login API (Supports Username or Mobile)
class LoginView(APIView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        fcm_token = request.data.get('fcm_token')

        # Check if user exists by username or mobile number
        user = User.objects.filter(Q(username=username) | Q(mobile_number=username) | Q(email=username)).first()
        if fcm_token:
            user.fcm_token = fcm_token
            user.save()

        if user and user.check_password(password):
            tokens = get_tokens_for_user(user)
            return Response({
                'refresh': tokens['refresh'],
                'token': tokens['token'],
                'user': AuthUserSerializer(user).data
            }, status=status.HTTP_200_OK)
        else:
            return Response(
                {
                'message': 'Incorrect username or password',
                'code': 102,
                }, 
                status=status.HTTP_401_UNAUTHORIZED
            )


# User Logout API (Blacklist Token)
class LogoutView(APIView):
    permission_classes = [AllowAny]
    # queryset = User.objects.all()

    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"error": "Refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"message": "Logged out successfully"}, status=status.HTTP_205_RESET_CONTENT)
        except Exception:
            return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)


# User Creations API
class CreateUserView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserCreateSerializer
    permission_classes = [IsAdminOnly]  # Only admins can create users

    def post(self, request, *args, **kwargs):
        try:
            # Only admins can create users
            if request.user.role != 'admin':
                return Response({"code": 403, "message": "Access denied. Only can create new users"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # check username for not student user
            username = request.data.get('username')
            mobile = request.data.get('mobile_number')
            email =  request.data.get('email')

            if username and User.objects.filter(username=username).exists():
                return Response({"code": 108, "message": "This user is already exist"},status=status.HTTP_400_BAD_REQUEST)

            if mobile and User.objects.filter(mobile_number=mobile).exists():
                return Response({"code": 122, "message": "This mobile number is already exist"},status=status.HTTP_400_BAD_REQUEST)

            if email and User.objects.filter(email=email).exists():
                return Response({"code": 123, "message": "This email is already exist"},status=status.HTTP_400_BAD_REQUEST)
        
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = serializer.save()  # This triggers the control number generation for students

            return Response({
                    "message": f"{user.role} created successfully", "user": serializer.data}
                    ,status=status.HTTP_201_CREATED
                )
        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"})


# User Edit API
class EditUserView(generics.UpdateAPIView):
    queryset = User.objects.all()
    serializer_class = UserCreateSerializer
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        # Extract `user_id` from request data
        user_id = request.data.get('user_id')

        if not user_id:
            return Response({"code" : 106, "message": "User ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"code": 107, "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        # Only Admins can update any user
        if request.user.role != 'admin':
            return Response({"code": 403, "message": "Only admins can update users"}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        # Ensure students don’t require passwords
        if user.role == 'student':
            serializer.validated_data.pop('password', None)

        serializer.save()
        return Response({"message": "User updated successfully", "user": serializer.data}, status=status.HTTP_200_OK)


# API FOR ACTIVATE AND DEACTIVATE USER
class ActivateDeactivateUserView(APIView):
    permission_classes = [IsAdminOnly]
    queryset = User.objects.all()

    def post(self, request, *args, **kwargs):
        try:
            # Only Admins can update any user
            if request.user.role != 'admin':
                return Response({"code": 403, "message": "Only admins can update users"}, status=status.HTTP_403_FORBIDDEN)


            # Get card ID from request body
            user_id = request.data.get("user_id")
            if not user_id:
                return Response({"code" : 106, "message": "User ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Check if card exists
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response({"code": 404, "message": "Card not found"}, status=status.HTTP_404_NOT_FOUND)

            # Toggle is_active based on request data
            action = request.data.get("action")  # Expected values: "activate" or "deactivate"
            if action == "activate":
                user.is_active = True
                message = "User is activated successful."
            elif action == "deactivate":
                user.is_active = False
                message = "User isdeactivated successfully."
            else:
                return Response({"code": 111, "message": "Invalid action. Use 'activate' or 'deactivate'."}, status=status.HTTP_400_BAD_REQUEST)

            user.save()
            return Response({"message": message, "card_id": user_id, "is_active": user.is_active}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"})

# FORGET PASSWORD VIEW
class ForgetPasswordView(APIView):
    permission_classes = [AllowAny]
    queryset = User.objects.all()

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

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({'code': 123, 'message': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'code': 124, 'message': 'User with this email does not exist.'}, status=status.HTTP_404_NOT_FOUND)

        password = self.generate_password(user.last_name)
        user.set_password(password)
        user.save()

        title = f"Reset Password"
        message = f"Hello {user.first_name}, your password was reset successfully. Your new password is {password}."
        Notification.objects.create(recipient=user,title=title, type='reminder', message=message)

        return Response({'message': 'Password reset link sent to your email.'}, status=status.HTTP_200_OK)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    queryset = User.objects.all()

    def post(self, request):
        try:
            old_password = request.data.get("old_password")
            new_password = request.data.get("new_password")

            if not old_password and not new_password:
                Response({'code': 126, 'message': 'Old password and new password are required.'}, status=status.HTTP_400_BAD_REQUEST)

            user = authenticate(username=request.user.username, password=old_password)
            if user is None:
                return Response({'code': 127,'message': 'Old password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)

            user.set_password(new_password)
            user.save()

            return Response({'message': 'Password changed successfully.'}, status=status.HTTP_200_OK)


        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"})