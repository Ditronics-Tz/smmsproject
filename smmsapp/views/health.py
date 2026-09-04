from django.db import connection
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAdminUser
from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
import time


@extend_schema(tags=['health'], auth=[])
class HealthView(APIView):
    """Liveness probe - never touches DB/Redis. For LB / Docker HEALTHCHECK."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok"}, status=http_status.HTTP_200_OK)


@extend_schema(tags=['health'])
class StatusView(APIView):
    """Dependency checks - staff only. Do NOT use for LB probe."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        checks = {}
        overall_ok = True

        # DB check
        try:
            start = time.monotonic()
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            checks["database"] = {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
        except Exception as e:
            checks["database"] = {"status": "error", "error": str(e)[:200]}
            overall_ok = False

        # Redis / Celery broker check (via redis-py if available)
        try:
            import redis
            r = redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2, socket_timeout=2)
            start = time.monotonic()
            r.ping()
            checks["redis"] = {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
        except ImportError:
            checks["redis"] = {"status": "skipped", "reason": "redis not installed"}
        except Exception as e:
            checks["redis"] = {"status": "error", "error": str(e)[:200]}
            overall_ok = False

        http_code = http_status.HTTP_200_OK if overall_ok else http_status.HTTP_503_SERVICE_UNAVAILABLE
        return Response({"status": "ok" if overall_ok else "degraded", "checks": checks}, status=http_code)
