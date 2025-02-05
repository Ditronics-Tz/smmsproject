from django.contrib.auth import authenticate
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.db.models import Q
from ..serializers.AuthSerializers import UserCreateSerializer, UserSerializer, LoginSerializer
from ..models import CustomUser as User, RFIDCard

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
                'user': UserSerializer(user).data
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
    permission_classes = [IsAuthenticated]  # Only admins can create users

    def post(self, request, *args, **kwargs):
        try:
            # Only admins can create users
            if request.user.role != 'admin':
                return Response(
                {
                    "code": 403,
                    "message": "Access denied. Only can create new users"
                },
                status=status.HTTP_403_FORBIDDEN
            )

            # Check Card number if already exist
            card_number = request.data.get('card_number')
            if card_number and RFIDCard.objects.filter(card_number=card_number).exists():
                return Response({
                    "code": 105,
                    "message": "This card already assign to another user"
                })

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = serializer.save()  # This triggers the control number generation for students

            return Response({
                "message": f"{user.role} created successfully", "user": serializer.data}
                ,status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response({
                "code": 500,
                "message": f'Something is wrong: {e}'
            },status=status.HTTP_400_BAD_REQUEST)
