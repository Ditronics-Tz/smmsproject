from django.urls import path
from smmsapp.views.dashboard import OperatorScanAnalyticsView

urlpatterns = [
    path('operators', OperatorScanAnalyticsView.as_view(), name='analytics-operators'),
]
