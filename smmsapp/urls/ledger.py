from django.urls import path

from smmsapp.views.ledger import (
    AccountStatementView,
    CardStatementView,
    JournalDetailView,
    JournalListView,
    LedgerIntegrityView,
    TrialBalanceView,
    FundStatementView,
)

urlpatterns = [
    path('journal', JournalListView.as_view(), name='journal-list'),
    path('journal/<uuid:entry_id>', JournalDetailView.as_view(), name='journal-detail'),
    path('cards/<uuid:card_id>/statement', CardStatementView.as_view(), name='card-statement'),
    path('funds/<int:fund_id>/statement', FundStatementView.as_view(), name='fund-statement'),
    path('accounts/<str:code>/statement', AccountStatementView.as_view(), name='account-statement'),
    path('trial-balance', TrialBalanceView.as_view(), name='trial-balance'),
    path('integrity', LedgerIntegrityView.as_view(), name='ledger-integrity'),
]
