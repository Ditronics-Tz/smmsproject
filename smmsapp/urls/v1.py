"""Versioned API v1 - all endpoints namespaced under /api/v1/."""
from django.urls import path, include

urlpatterns = [
    path('config/', include('smmsapp.urls.config')),
    path('auth/', include('smmsapp.urls.auth')),
    path('dashboard/', include('smmsapp.urls.dashboard')),
    path('analytics/', include('smmsapp.urls.analytics')),
    path('resources/', include('smmsapp.urls.resources')),
    path('sessions/', include('smmsapp.urls.sessions')),
    path('list/', include('smmsapp.urls.lists')),
    path('wallet/', include('smmsapp.urls.wallet')),
    path('imports/', include('smmsapp.urls.imports')),
    path('exports/', include('smmsapp.urls.exports')),
    path('audit/', include('smmsapp.urls.audit')),
    path('sms/', include('smmsapp.urls.sms')),
]
