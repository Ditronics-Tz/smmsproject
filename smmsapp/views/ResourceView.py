from django.contrib.auth import authenticate
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, DjangoModelPermissionsOrAnonReadOnly, IsAuthenticated, IsAdminUser
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ..serializers.ResourceSerializers import FullStudentSerializer, UserSerializer, FullParentSerializer, FullOperatorSerializer, SchoolSerializer, FullAdminSerializer
from ..models import CustomUser as User, School
from ..permissions.CustomPermissions import IsAdminOrParent, IsAdminOnly

# ----- API FOR GET SCHOOL -----
class SchoolListView(APIView, PageNumberPagination):
    permission_classes = [IsAuthenticated]
    page_size = 20

    def post(self, request, *args, **kwargs):
        search_query = request.data.get("search").strip()
        school = School.objects.all().order_by('name')

        if search_query:
            school = school.filter(
                Q(name__icontains=search_query) | Q(location__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(school, request, view=self)
        if result is not None:
            serializer =SchoolSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = UserSerializer(school, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
# ----- API TO ADD SCHOOL ----
class CreateSchoolView(generics.CreateAPIView):
    queryset = School.objects.all()
    serializer_class = SchoolSerializer
    permission_classes = [IsAuthenticated]


# ----- API FOR GET STUDENT LIST -----
class UserListView(APIView, PageNumberPagination):
    permission_classes = [IsAuthenticated]  #Requires authentication
    page_size = 50 

    def post(self, request, *args, **kwargs):
        search_query = request.data.get("search").strip()
        role = request.data.get("role")
        users = User.objects.filter(role=role).exclude(id=request.user.id).order_by("first_name")  # Filter by role

        if search_query:
            users = users.filter(
                Q(first_name__icontains=search_query) | Q(last_name__icontains=search_query) | Q(middle_name__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(users, request, view=self)
        if result is not None:
            serializer =UserSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

# ----- API FOR FETCH STUDENT DATA -----
class StudentDetailView(generics.RetrieveAPIView):
    queryset = User.objects.filter(role='student')
    serializer_class = FullStudentSerializer,
    permission_class = [IsAdminOrParent]

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role not in ['admin','parent']:
            return Response(
                {
                    "code": 403,
                    "message": "Access denied. Only admins and parents can view student details"
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        student_id = request.data.get("student_id")

        if not student_id:
            return Response({
                "code": 104,
                "message": "Student id required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        student = get_object_or_404(User, id=student_id, role = 'student')
        serializer = FullStudentSerializer(student)

        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR FETCH PARENT DATA -----
class ParentDetailView(generics.RetrieveAPIView):
    queryset = User.objects.filter(role='parent')
    serializer_class = FullParentSerializer,
    permission_class = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role != 'admin':
            return Response(
                {
                    "code": 403,
                    "message": "Access denied. Only admins can view parents details"
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        parent_id = request.data.get("parent_id")

        if not parent_id:
            return Response({
                "code": 104,
                "message": "Parent id required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        parent = get_object_or_404(User, id=parent_id, role = 'parent')
        serializer = FullParentSerializer(parent)

        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR FETCH OPERATORS DATA -----
class OperatorDetailView(generics.RetrieveAPIView):
    queryset = User.objects.filter(role='operator')
    serializer_class = FullOperatorSerializer,
    permission_class = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role != 'admin':
            return Response(
                {
                    "code": 403,
                    "message": "Access denied. Only admins can view operator details"
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        operator_id = request.data.get("operator_id")

        if not operator_id:
            return Response({
                "code": 104,
                "message": "Parent id required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        operator = get_object_or_404(User, id=operator_id, role = 'operator')
        serializer = FullOperatorSerializer(operator)

        return Response(serializer.data, status=status.HTTP_200_OK)
    
class AdminDetailsView(generics.RetrieveAPIView):
    queryset = User.objects.filter(role='admin')
    serializer_class = FullAdminSerializer
    permission_classes = [IsAdminUser]

    def post(self, request, *args, **kwags):
        if not request.user.is_authenticated or request.user.role != 'admin':
            return Response({
                "code": 403,
                "messsage": "Access denied!, Only super admin can view admins details"
            },status=status.HTTP_403_FORBIDDEN)
        
        admin_id = request.data.get('admin_id')
        
        if not admin_id:
            return Response({"code": 104, "message": "Admin ID required"},status=status.HTTP_400_BAD_REQUEST)
        
        admin = get_object_or_404(User, id=admin_id, role= 'admin')
        serializer  = FullAdminSerializer(admin)

        return Response(serializer.data, status=status.HTTP_200_OK)


