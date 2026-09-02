from django.contrib.auth import authenticate
from django.core.mail import send_mail
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.db.models import Q
import random
import string
import secrets
import hashlib
from datetime import timedelta
from django.utils import timezone
from ..serializers.auth import (
    UserCreateSerializer, AuthUserSerializer, LoginSerializer,
    PasswordResetRequestSerializer, PasswordResetConfirmSerializer,
)
from ..models import CustomUser as User, RFIDCard, Notification, PasswordResetToken
from ..permissions.roles import IsAdminOnly, IsAdminOrParent

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
    throttle_scope = 'login'

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        fcm_token = request.data.get('fcm_token')

        # Check if user exists by username or mobile number
        user = User.objects.filter(Q(username=username) | Q(mobile_number=username) | Q(email=username)).first()
        if not (user and user.check_password(password)):
            return Response(
                {
                'message': 'Incorrect username or password',
                'code': 102,
                }, 
                status=status.HTTP_401_UNAUTHORIZED
            )

        tokens = get_tokens_for_user(user)
        if fcm_token:
            user.fcm_token = fcm_token
            user.save()
        return Response({
            'refresh': tokens['refresh'],
            'token': tokens['token'],
            'user': AuthUserSerializer(user).data
        }, status=status.HTTP_200_OK)


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
    """Request a self-service password reset.

    Generates a single-use, expiring token, hashes it for storage, and emails
    the user a reset link. Always returns the same generic success response
    whether or not the email exists (enumeration-resistant, paired with the
    existing 'forget_password' throttle). Never generates or emails a plaintext
    password.
    """
    permission_classes = [AllowAny]
    throttle_scope = 'forget_password'
    serializer_class = PasswordResetRequestSerializer
    RESET_LINK_TTL = timedelta(minutes=30)

    @staticmethod
    def _hash_token(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response({'code': 123, 'message': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email'].strip().lower()

        # Always return the same generic message regardless of whether the user
        # exists, to avoid leaking which emails have accounts (DIT-64 pairing).
        generic_message = 'If an account exists for this email, a reset link has been sent.'
        user = User.objects.filter(email__iexact=email).first()

        if user is not None and user.email:
            # Invalidate any prior unused tokens for this user so only one is live.
            PasswordResetToken.objects.filter(user=user, used_at__isnull=True).delete()

            raw_token = secrets.token_urlsafe(32)
            PasswordResetToken.objects.create(
                user=user,
                token_hash=self._hash_token(raw_token),
                expires_at=timezone.now() + self.RESET_LINK_TTL,
            )

            try:
                send_mail(
                    subject="Reset Your SMMS Password",
                    message=(
                        f"Hello {user.first_name},\n\n"
                        f"We received a request to reset your password. Use the link below "
                        f"to set a new password. This link expires in 30 minutes and can "
                        f"only be used once:\n\n"
                        f"Reset token: {raw_token}\n\n"
                        f"If you did not request this, you can safely ignore this email.\n\n"
                        f"Thank you,\nSMMS Application"
                    ),
                    from_email=None,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception:
                # Email delivery failed — do not leak account existence. The
                # request still reports generic success; admin can re-issue.
                pass

            Notification.objects.create(
                recipient=user,
                title="Reset Password",
                type='reminder',
                message="A password reset link was sent to your registered email.",
            )

        return Response({'message': generic_message}, status=status.HTTP_200_OK)


# CONFIRM PASSWORD RESET VIEW
class ConfirmPasswordResetView(APIView):
    """Validate a single-use, expiring reset token and set a new password."""
    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer
    RESET_LINK_TTL = timedelta(minutes=30)

    @staticmethod
    def _hash_token(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'code': 400, 'message': 'token and new_password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']

        token_hash = self._hash_token(token)
        try:
            reset = PasswordResetToken.objects.select_related('user').get(token_hash=token_hash)
        except PasswordResetToken.DoesNotExist:
            return Response(
                {'code': 124, 'message': 'Invalid or expired reset token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Single-use: already used
        if reset.used_at is not None:
            return Response(
                {'code': 124, 'message': 'This reset token has already been used.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Expired
        if timezone.now() > reset.expires_at:
            return Response(
                {'code': 124, 'message': 'This reset token has expired.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = reset.user
        user.set_password(new_password)
        user.save()

        # Mark used and invalidate any other outstanding tokens for this user.
        reset.used_at = timezone.now()
        reset.save(update_fields=['used_at'])
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).delete()

        Notification.objects.create(
            recipient=user,
            title="Password Changed",
            type='reminder',
            message="Your password was reset successfully.",
        )

        return Response({'message': 'Password reset successfully. You can now log in.'}, status=status.HTTP_200_OK)


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