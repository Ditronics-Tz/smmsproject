from rest_framework.permissions import BasePermission

from smmsapp.services.features import is_enabled


def FeatureEnabled(key):
    """Permission-class factory for endpoints guarded by a feature flag."""
    class FeatureEnabledPermission(BasePermission):
        feature_key = key

        def has_permission(self, request, view):
            # The existing scanner is RFID-first. Only requests explicitly
            # using the optional NFC UID flow require NFC_SCAN.
            if key == 'NFC_SCAN':
                try:
                    request_data = request.data
                except Exception:
                    request_data = getattr(getattr(request, '_request', None), 'POST', {})
                if 'card_uid' not in request_data:
                    return True
            if is_enabled(key):
                return True
            self.message = {
                'code': 'FEATURE_DISABLED',
                'message': f'The {key} feature is disabled for this deployment.',
            }
            return False

    FeatureEnabledPermission.__name__ = f'{key.title().replace("_", "")}FeatureEnabledPermission'
    return FeatureEnabledPermission
