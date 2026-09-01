from django.urls import path
from . import views as wallet_views

app_name = 'wallet'

urlpatterns = [
    # ------- Deposit (top-up) flow -------
    path('deposit/create', wallet_views.CreateDepositView.as_view(), name='create-deposit'),
    path('deposit/list', wallet_views.DepositListView.as_view(), name='list-deposits'),
    path('deposit/process', wallet_views.ProcessDepositView.as_view(), name='process-deposit'),

    # ------- Ledger (chronological audit trail) -------
    path('ledger/card', wallet_views.CardLedgerView.as_view(), name='card-ledger'),

    # ------- Transaction reversal (void) -------
    path('transaction/reverse', wallet_views.ReverseTransactionView.as_view(), name='reverse-transaction'),
]