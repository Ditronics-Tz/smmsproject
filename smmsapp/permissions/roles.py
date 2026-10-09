from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import status

class IsAdminParentOrStaff(BasePermission):
    """Allow admins, parents, and staff to reach views with object-level checks."""
    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.role in ['admin','parent','staff']:
            return True
        return False
    
class IsAdminOnly(BasePermission):
    """Allow only accounts whose application role is admin."""
    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.role == 'admin':
            return True
        return False
    
class IsOperator(BasePermission):
    """Allow only operator accounts."""
    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.role == 'operator':
            return True
        return False

class IsAdminOrOperator(BasePermission):
    """Allow admins and operators."""
    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.role in ['admin','operator']:
            return True
        return False

class IsAdminOperatorOrParent(BasePermission):
    """Allow admins, operators, and parents."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ['admin', 'operator', 'parent']
