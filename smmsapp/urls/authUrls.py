from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from ..views.AuthViews import LoginView, LogoutView, CreateUserView, EditUserView

urlpatterns = [
    path('login', LoginView.as_view(), name='login'),
    # path('register', RegisterView.as_view(), name='register'),
    path('create-user',CreateUserView.as_view(), name='create-user'),
    path('edit-user',EditUserView.as_view(), name='edit-user'),
    path('logout', LogoutView.as_view(), name='logout'),
    path('token/refresh', TokenRefreshView.as_view(), name='token_refresh'),
    
]
