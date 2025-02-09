from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from ..views.ResourceView import UserListView, StudentDetailView, ParentDetailView, OperatorDetailView, SchoolListView, CreateSchoolView

urlpatterns = [
    path('users-list/', UserListView.as_view(), name='users-list'),
    path('student-details', StudentDetailView.as_view(), name='student-details'),
    path('parent-details', ParentDetailView.as_view(), name='parent-details'),
    path('operator-details', OperatorDetailView.as_view(), name='operator_details'),
    path('school-list/', SchoolListView.as_view(), name='school-list'),
    path('create-school', CreateSchoolView.as_view(), name='create-school')
]
