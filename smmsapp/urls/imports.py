from django.urls import path
from ..views.imports import (
    ImportTemplateView, ImportUploadView, ImportCommitView,
)

urlpatterns = [
    path('template', ImportTemplateView.as_view(), name='import-template'),
    path('upload', ImportUploadView.as_view(), name='import-upload'),
    path('commit', ImportCommitView.as_view(), name='import-commit'),
]
