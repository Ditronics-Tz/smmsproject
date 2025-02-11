from django.contrib.auth import authenticate
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.db.models import Q
from ..serializers.AuthSerializers import UserCreateSerializer, AuthUserSerializer, LoginSerializer
from ..models import CustomUser as User, RFIDCard
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

        # Check if user exists by username or mobile number
        user = User.objects.filter(Q(username=username) | Q(mobile_number=username)).first()

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
    queryset = User.objects.all()

    def post(self, request, *args, **kwargs):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"message": "Logged out successfully"}, status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
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
            if username and User.objects.filter(username=username).exists():
                return Response({"code": 108, "message": "This user is already exist"},status=status.HTTP_400_BAD_REQUEST)


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