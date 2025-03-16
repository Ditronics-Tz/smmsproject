from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from ..views.AuthViews import *

urlpatterns = [
    path('login', LoginView.as_view(), name='login'),
    # path('register', RegisterView.as_view(), name='register'),
    path('create-user',CreateUserView.as_view(), name='create-user'),
    path('edit-user',EditUserView.as_view(), name='edit-user'),
    path('activate-deactivate-user', ActivateDeactivateUserView.as_view(), name='activate-deactivate-user'),
    path('logout', LogoutView.as_view(), name='logout'),
    path('token/refresh', TokenRefreshView.as_view(), name='token_refresh'),
    path('forget-password', ForgetPasswordView.as_view(), name='forget-password'),
    path('change-password', ChangePasswordView.as_view(), name='change-password'),
]
