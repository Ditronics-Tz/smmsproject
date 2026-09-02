from django.urls import path
from ..views.dashboard import *
from ..views.alerts import BalanceThresholdView

urlpatterns = [
    path('counts', CountsView.as_view(), name='counts'),
    path('sales-summary', SalesSummaryView.as_view(), name='sales-summary'),
    path('sales-trend', WeeklySalesTrendView.as_view(), name='sales-trend'),
    path('end-of-day-report', EndOfDayReportView.as_view(), name='end-of-day-report'),
    path('parent-students', ParentStudentsView.as_view(), name='parent-students'),
    path('children-spend', ChildSpendView.as_view(), name='children-spend'),
    path('balance-threshold', BalanceThresholdView.as_view(), name='balance-threshold'),
    path('staff-view', StaffView.as_view(), name='staff-view'),
    path('last-session', LastSessionDetailsView.as_view(), name='last-session')
]