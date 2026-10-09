from django.urls import path

from ..views.exports import (
    TransactionExportView, StudentExportView, DepositExportView, ExportDownloadView,
    AnalyticsSalesExportView, AnalyticsWalletHealthExportView, AnalyticsOperatorsExportView,
)

urlpatterns = [
    path('transactions', TransactionExportView.as_view(), name='export-transactions'),
    path('students', StudentExportView.as_view(), name='export-students'),
    path('deposits', DepositExportView.as_view(), name='export-deposits'),
    path('analytics_sales', AnalyticsSalesExportView.as_view(), name='export-analytics-sales'),
    path('analytics_wallet_health', AnalyticsWalletHealthExportView.as_view(), name='export-analytics-wallet-health'),
    path('analytics_operators', AnalyticsOperatorsExportView.as_view(), name='export-analytics-operators'),
    path('download/<str:token>', ExportDownloadView.as_view(), name='export-download'),
]
