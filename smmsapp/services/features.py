"""Database-overridable, short-lived feature flag lookup."""
from django.conf import settings
from django.core.cache import cache

_CACHE_KEY = 'smmsapp:feature-flags:v1'
_CACHE_TIMEOUT = 60


def clear_feature_cache(*args, **kwargs):
    cache.delete(_CACHE_KEY)


def all_flags():
    known_keys = set(getattr(settings, 'FEATURES_DEFAULT', {}))
    from smmsapp.models import FeatureFlag

    rows = dict(FeatureFlag.objects.filter(key__in=known_keys).values_list('key', 'enabled'))
    return {
        key: rows.get(key, bool(settings.FEATURES_DEFAULT.get(key, False)))
        for key in sorted(known_keys)
    }


def is_enabled(key):
    """Return a flag value; raise KeyError for keys not declared in settings."""
    defaults = getattr(settings, 'FEATURES_DEFAULT', {})
    if key not in defaults:
        raise KeyError(key)

    flags = cache.get(_CACHE_KEY)
    if flags is None:
        flags = all_flags()
        cache.set(_CACHE_KEY, flags, _CACHE_TIMEOUT)
    return flags[key]
