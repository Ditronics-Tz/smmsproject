from django.urls import path
from ..views.SessionView import *

urlpatterns = [
    path('start-session', StartScanSessionView.as_view(), name='start-session'),
    path('end-session', EndScanSessionView.as_view(), name='end-session'),
    path('active-session', ActiveSessionView.as_view(), name='active-session'),
    path('session-list', SessionListView.as_view(), name='session-list'),
    path('scan-card', ScanRFIDCardView.as_view(), name='scan-card'),
    path('scanned-data/', ScannedDataListView.as_view(), name='scanned-data'),
    path('transaction-list/', TransactionListView.as_view(), name='transaction-list'),
]
