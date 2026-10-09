"""Database-overridable, short-lived feature flag lookup."""
import hashlib
import json

from django.conf import settings
from django.core.cache import cache

_CACHE_KEY = 'smmsapp:feature-flags:v1'
_CACHE_TIMEOUT = 60


def _cache_key():
    defaults = getattr(settings, 'FEATURES_DEFAULT', {})
    fingerprint = hashlib.sha256(
        json.dumps(defaults, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()[:12]
    return f'{_CACHE_KEY}:{fingerprint}'


def clear_feature_cache(*args, **kwargs):
    cache.delete(_cache_key())


def all_flags():
    known_keys = set(getattr(settings, 'FEATURE_KEYS', ())) | set(getattr(settings, 'FEATURES_DEFAULT', {}))
    from smmsapp.models import FeatureFlag

    rows = dict(FeatureFlag.objects.filter(key__in=known_keys).values_list('key', 'enabled'))
    return {
        key: rows.get(key, bool(getattr(settings, 'FEATURES_DEFAULT', {}).get(key, False)))
        for key in sorted(known_keys)
    }


def is_enabled(key):
    """Return a flag value; raise KeyError for keys not declared in settings."""
    defaults = getattr(settings, 'FEATURES_DEFAULT', {})
    known_keys = set(getattr(settings, 'FEATURE_KEYS', ())) | set(defaults)
    if key not in known_keys:
        raise KeyError(key)

    feature_key = key
    cache_key = _cache_key()
    flags = cache.get(cache_key)
    if flags is None:
        flags = all_flags()
        cache.set(cache_key, flags, _CACHE_TIMEOUT)
    return flags[feature_key]
