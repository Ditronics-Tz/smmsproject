from django.urls import path

from smmsapp.views.menu import (
    DailyMenuCopyView,
    DailyMenuDetailView,
    DailyMenuListCreateView,
    TodayMenuView,
)

urlpatterns = [
    path('daily', DailyMenuListCreateView.as_view(), name='daily-menu-list-create'),
    path('daily/<uuid:menu_id>', DailyMenuDetailView.as_view(), name='daily-menu-detail'),
    path('copy', DailyMenuCopyView.as_view(), name='daily-menu-copy'),
    path('today', TodayMenuView.as_view(), name='daily-menu-today'),
]
