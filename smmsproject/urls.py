"""
URL configuration for smmsproject project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from . import settings
from smmsapp.views.health import HealthView, StatusView

urlpatterns = [
    path('admin-auth/', admin.site.urls),
    path('health', HealthView.as_view(), name='health'),
    path('health/', HealthView.as_view(), name='health-slash'),
    path('status', StatusView.as_view(), name='status'),
    path('status/', StatusView.as_view(), name='status-slash'),
    path('',include('smmsapp.urls.admin')),
    path('api-auth/', include('rest_framework.urls')),
    # Legacy unversioned paths (dual-serve during migration)
    path('auth/', include('smmsapp.urls.auth')),
    path('dashboard/', include('smmsapp.urls.dashboard')),
    path('resources/', include("smmsapp.urls.resources")),
    path('sessions/', include("smmsapp.urls.sessions")),
    path('list/',include("smmsapp.urls.lists")),
    path('wallet/', include("smmsapp.urls.wallet")),
    path('imports/', include("smmsapp.urls.imports")),
    path('exports/', include("smmsapp.urls.exports")),
    path('audit/', include("smmsapp.urls.audit")),
    path('sms/', include("smmsapp.urls.sms")),
    # Versioned API
    path('api/v1/', include('smmsapp.urls.v1')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Spectacular schema/docs (staff-only) - added conditionally if installed
try:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
    from django.contrib.admin.views.decorators import staff_member_required
    urlpatterns += [
        path('api/schema/', staff_member_required(SpectacularAPIView.as_view()), name='schema'),
        path('api/docs/', staff_member_required(SpectacularSwaggerView.as_view(url_name='schema')), name='swagger-ui'),
        path('api/redoc/', staff_member_required(SpectacularRedocView.as_view(url_name='schema')), name='redoc'),
    ]
except ImportError:
    pass
