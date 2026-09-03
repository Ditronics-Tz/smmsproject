"""Versioned API v1 - all endpoints namespaced under /api/v1/."""
from django.urls import path, include

urlpatterns = [
    path('auth/', include('smmsapp.urls.auth')),
    path('dashboard/', include('smmsapp.urls.dashboard')),
    path('resources/', include('smmsapp.urls.resources')),
    path('sessions/', include('smmsapp.urls.sessions')),
    path('list/', include('smmsapp.urls.lists')),
    path('wallet/', include('smmsapp.urls.wallet')),
    path('imports/', include('smmsapp.urls.imports')),
    path('exports/', include('smmsapp.urls.exports')),
    path('audit/', include('smmsapp.urls.audit')),
]
