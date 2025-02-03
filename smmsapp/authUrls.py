from django.urls import path

from .views import  AuthViews, adminViews

urlpatterns = [
    # ---- AUTHENTICATIONS PATH ---------
    path('login/', AuthViews.LoginView.as_view(), name='login'),
]