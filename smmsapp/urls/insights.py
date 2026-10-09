from django.urls import path

from smmsapp.views.insights import (
    AnomaliesView, AtRiskStudentsView, DormantCardsView, ForecastView,
    ResolveAnomalyView,
)

urlpatterns = [
    path('forecast', ForecastView.as_view(), name='insights-forecast'),
    path('at-risk', AtRiskStudentsView.as_view(), name='insights-at-risk'),
    path('anomalies', AnomaliesView.as_view(), name='insights-anomalies'),
    path('anomalies/<uuid:flag_id>/resolve', ResolveAnomalyView.as_view(), name='insights-resolve'),
    path('dormant-cards', DormantCardsView.as_view(), name='insights-dormant-cards'),
]
