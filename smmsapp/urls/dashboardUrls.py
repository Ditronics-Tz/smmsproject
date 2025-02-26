from django.urls import path
from ..views.DashboardView import *

urlpatterns = [
    path('counts', CountsView.as_view(), name='counts'),
    path('sales-summary', SalesSummaryView.as_view(), name='sales-summary'),
    path('sales-trend', WeeklySalesTrendView.as_view(), name='sales-trend'),
    path('end-of-day-report', EndOfDayReportView.as_view(), name='end-of-day-report'),
    path('parent-students', ParentStudentsView.as_view(), name='parent-students'),
    path('staff-view', StaffView.as_view(), name='staff-view'),
    path('last-session', LastSessionDetailsView.as_view(), name='last-session')
]