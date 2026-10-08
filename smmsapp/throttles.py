from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class OperatorScanThrottle(SimpleRateThrottle):
    scope = 'operator_scan'

    def __init__(self):
        self.rate = f"{getattr(settings, 'SCAN_THROTTLE_RATE', 120)}/min"
        super().__init__()

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated or request.user.role != 'operator':
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk}
