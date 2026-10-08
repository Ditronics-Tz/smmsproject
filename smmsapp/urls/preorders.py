from django.urls import path

from smmsapp.views.preorders import (
    PreOrderCancelView, PreOrderCreateView, PreOrderListView, PreOrderMenuView,
    PreOrderSessionView, PreOrderSummaryView,
)

urlpatterns = [
    path('menu', PreOrderMenuView.as_view(), name='preorder-menu'),
    path('create', PreOrderCreateView.as_view(), name='preorder-create'),
    path('cancel', PreOrderCancelView.as_view(), name='preorder-cancel'),
    path('list', PreOrderListView.as_view(), name='preorder-list'),
    path('summary', PreOrderSummaryView.as_view(), name='preorder-summary'),
    path('session', PreOrderSessionView.as_view(), name='preorder-session'),
]
