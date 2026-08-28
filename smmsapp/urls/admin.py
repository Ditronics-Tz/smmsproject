from django.urls import path

from ..views import admin

urlpatterns = [
    path('', admin.index, name="home"),
]