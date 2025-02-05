from django.contrib.auth import authenticate
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, DjangoModelPermissionsOrAnonReadOnly, IsAuthenticated
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ..serializers.ResourceSerializers import FullStudentSerializer, StudentSerializer
from ..models import CustomUser as User
from ..permissions.CustomPermissions import IsAdminOrParent

# ----- API FOR GET STUDENT LIST -----
class StudentListView(APIView, PageNumberPagination):
    permission_classes = [IsAuthenticated]  # ✅ Requires authentication

    def post(self, request, *args, **kwargs):
        search_query = request.data.get("search").strip()
        students = User.objects.filter(role='student')  # ✅ Filter by role

        if search_query:
            students = students.filter(first_name__icontains=search_query)
        
        result = self.paginate_queryset(students, request, view=self)
        serializer = StudentSerializer(students, many=True)
        return self.get_paginated_response(serializer.data)
    

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


