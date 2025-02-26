from django.contrib.auth import authenticate
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, DjangoModelPermissionsOrAnonReadOnly, IsAuthenticated, IsAdminUser
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ..serializers import *
from ..models import *
from ..permissions.CustomPermissions import IsAdminOrParent, IsAdminOnly

# --- api to return all active parent
class AllParentListView(generics.ListAPIView):
    queryset = CustomUser.objects.filter(role="parent", is_active=True)
    serializer_class = ParentSerializer
    permission_classes = [IsAuthenticated]
    page_size = None

#  --- api to return all active students 
class AllStudentListView(generics.ListAPIView):
    queryset = CustomUser.objects.filter(role='student', is_active=True)
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]
    page_size = None
    
#  --- api to return all active students 
class AllStaffListView(generics.ListAPIView):
    queryset = CustomUser.objects.filter(role='staff', is_active=True)
    serializer_class = StaffSerializer
    permission_classes = [IsAuthenticated]
    page_size = None

# --- api to return all cards active
class AllCardListView(generics.ListAPIView):
    queryset = RFIDCard.objects.filter(is_active=True)
    serializer_class = RFIDCardSerializer
    permission_classes = [IsAuthenticated]
    page_size = None

# --- api to return all school list
class AllSchoooListView(generics.ListAPIView):
    queryset = School.objects.all()
    serializer_class = SchoolSerializer
    permission_classes = [IsAuthenticated]
    page_size = None

# --- api to return all items
class AllCanteenItemView(generics.ListAPIView):
    queryset = CanteenItem.objects.all()
    serializer_class = CanteenItemSerializer
    permission_classes = [IsAuthenticated]
    page_size = None
