from django.urls import path

from smmsapp.views.config import FeatureFlagUpdateView, FeaturesConfigView, PublicConfigView

urlpatterns = [
    path('public', PublicConfigView.as_view(), name='public-config'),
    path('features', FeaturesConfigView.as_view(), name='features-config'),
    path('features/<str:key>', FeatureFlagUpdateView.as_view(), name='feature-flag-update'),
]
