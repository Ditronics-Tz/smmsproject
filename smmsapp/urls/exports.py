from django.urls import path

from ..views.exports import (
    TransactionExportView, StudentExportView, DepositExportView, ExportDownloadView,
)

urlpatterns = [
    path('transactions', TransactionExportView.as_view(), name='export-transactions'),
    path('students', StudentExportView.as_view(), name='export-students'),
    path('deposits', DepositExportView.as_view(), name='export-deposits'),
    path('download/<str:token>', ExportDownloadView.as_view(), name='export-download'),
]
