from django.urls import path
from smmsapp.views.analytics import (
    ClassesAnalyticsView, OperatorsAnalyticsView, PenaltiesAnalyticsView,
    SalesAnalyticsView, WalletHealthView,
)

urlpatterns = [
    path('sales', SalesAnalyticsView.as_view(), name='analytics-sales'),
    path('wallet-health', WalletHealthView.as_view(), name='analytics-wallet-health'),
    path('operators', OperatorsAnalyticsView.as_view(), name='analytics-operators'),
    path('classes', ClassesAnalyticsView.as_view(), name='analytics-classes'),
    path('penalties', PenaltiesAnalyticsView.as_view(), name='analytics-penalties'),
]
