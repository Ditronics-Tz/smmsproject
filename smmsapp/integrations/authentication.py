import hashlib
import hmac

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from smmsapp.models import IntegrationKey


class ApiKeyAuthentication(BaseAuthentication):
    """Authenticate only integration views using a one-time-shown API key."""

    keyword = b"Api-Key"

    def authenticate(self, request):
        raw_key = request.headers.get("X-API-Key")
        authorization = request.META.get("HTTP_AUTHORIZATION", "").encode()
        if not raw_key and authorization:
            parts = authorization.split()
            if len(parts) == 2 and hmac.compare_digest(parts[0].lower(), self.keyword.lower()):
                raw_key = parts[1].decode("utf-8", errors="ignore")
        if not raw_key:
            return None

        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        key = IntegrationKey.objects.select_related("created_by", "created_by__school").filter(
            key_hash=key_hash, revoked_at__isnull=True,
        ).first()
        if key is None or key.created_by is None or not key.created_by.is_active or key.created_by.school_id is None:
            raise AuthenticationFailed("Invalid or revoked integration key.")
        # A constant-time comparison protects against accidental hash storage
        # mismatches and keeps the raw token out of model/log serialization.
        if not hmac.compare_digest(key.key_hash, key_hash):
            raise AuthenticationFailed("Invalid integration key.")
        IntegrationKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        request.integration_key = key
        return key.created_by, key

    def authenticate_header(self, request):
        return "Api-Key"
