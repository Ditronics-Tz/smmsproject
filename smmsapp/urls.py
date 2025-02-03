from django.urls import path

from .views import  AuthViews, adminViews

urlpatterns = [
    path('', adminViews.index, name="home"),
]