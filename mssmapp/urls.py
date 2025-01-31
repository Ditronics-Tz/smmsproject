from django.urls import path

from .views import adminViews

urlpatterns = [
    path("", adminViews.index, name="index"),
]