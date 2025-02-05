from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from ..views.ResourceView import StudentListView, StudentDetailView

urlpatterns = [
    path('students-list/', StudentListView.as_view(), name='students-list'),
    path('student-details', StudentDetailView.as_view(), name='student-details'),
]
