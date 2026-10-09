from django.urls import path

from smmsapp.views.stock import StockAdjustView, StockListView

urlpatterns = [
    path('', StockListView.as_view(), name='stock-list'),
    path('adjust', StockAdjustView.as_view(), name='stock-adjust'),
]
