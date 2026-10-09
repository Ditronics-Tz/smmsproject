from rest_framework.throttling import SimpleRateThrottle
from django.conf import settings


class IntegrationKeyThrottle(SimpleRateThrottle):
    scope = "integration"

    def get_rate(self):
        configured_rates = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {})
        return configured_rates.get(self.scope)

    def get_cache_key(self, request, view):
        key = getattr(request, "auth", None)
        if key is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": key.pk}
