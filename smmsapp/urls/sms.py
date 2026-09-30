from django.urls import path
from ..views.sms import (
    SMSLogListView, SMSLogListViewSlashAlias, SMSOptOutView, SMSOptOutViewSlashAlias,
)

urlpatterns = [
    path("opt-out", SMSOptOutView.as_view(), name="sms-opt-out"),
    path("opt-out/", SMSOptOutViewSlashAlias.as_view(), name="sms-opt-out-slash"),
    path("logs", SMSLogListView.as_view(), name="sms-logs"),
    path("logs/", SMSLogListViewSlashAlias.as_view(), name="sms-logs-slash"),
]
