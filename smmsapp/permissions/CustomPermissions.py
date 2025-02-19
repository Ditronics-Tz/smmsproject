from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import status

class IsAdminOrParent(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.role in ['admin','parent']:
            return True
        return False
    
class IsAdminOnly(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.role == 'admin':
            return True
        return False
    
class IsOperator(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.role == 'operator':
            return True
        return False

class IsAdminOrOperator(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.role in ['admin','operator']:
            return True
        return False