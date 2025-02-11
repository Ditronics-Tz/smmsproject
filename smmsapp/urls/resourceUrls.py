from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from ..views.ResourceView import *

urlpatterns = [
    # User Urls
    path('users-list/', UserListView.as_view(), name='users-list'),
    path('inactive-users-list/', InactiveUserListView.as_view(), name='inactive-users-list'),

    # User details Urls
    path('student-details', StudentDetailView.as_view(), name='student-details'),
    path('parent-details', ParentDetailView.as_view(), name='parent-details'),
    path('operator-details', OperatorDetailView.as_view(), name='operator_details'),
    path('admin-details', AdminDetailsView.as_view(), name='admin-details'),

    # School Urls
    path('school-list/', SchoolListView.as_view(), name='school-list'),
    path('delete-school', DeleteSchoolView.as_view(), name='delete-school'),
    path('create-school', CreateSchoolView.as_view(), name='create-school'),

    # Canteen Items Urls
    path('create-item', CreateItemView.as_view(), name='create-item'),
    path('item-list/', ItemListView.as_view(), name='item-list'),
    path('delete-item', DeleteItemView.as_view(), name='delete-item'),
    path('edit-item', EditItemView.as_view(), name='edit-item'),

    # Card Urls
    path('create-card', CreateCardView.as_view(), name='create-card'),
    path('edit-card', EditCardView.as_view(), name='edit-card'),
    path('card-list/', CardListView.as_view(), name='card-list'),
    path('card-details', CardDetailsView.as_view(), name='card-details'),
    path('activate-deactivate-card', ActivateDeactivateCardView.as_view(), name='activate-deactivate-card')
]
