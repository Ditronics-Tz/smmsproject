from django.urls import path
from ..views.ListView import *

urlpatterns = [
    path('schools', AllSchoooListView.as_view(), name='schools' ),
    path('parents', AllParentListView.as_view(), name='parents'),
    path('students', AllStudentListView.as_view(), name='students'),
    path('canteen-items', AllCanteenItemView.as_view(), name='canteen-items'),
    path('cards', AllCardListView.as_view(), name='cards')
]