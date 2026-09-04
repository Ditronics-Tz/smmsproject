from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

def _get_request_meta():
    try:
        from smmsapp.middleware.audit import get_current_request
        req = get_current_request()
        if req is None:
            return None, "", ""
        xff = req.META.get('HTTP_X_FORWARDED_FOR', '')
        ip = xff.split(',')[0].strip() if xff else req.META.get('REMOTE_ADDR')
        return req.user if getattr(req, 'user', None) and req.user.is_authenticated else None, ip, req.path
    except Exception:
        return None, "", ""

def _serialize(obj):
    if obj is None:
        return None
    data = {}
    for f in obj._meta.get_fields():
        if f.concrete and not f.many_to_many and not f.auto_created:
            try:
                val = getattr(obj, f.name)
                # avoid serializing file objects fully
                if hasattr(val, 'url'):
                    val = str(val)
                else:
                    val = str(val) if val is not None else None
                data[f.name] = val
            except Exception:
                continue
    return data

def log_action(action, obj=None, before=None, after=None, actor=None, request=None):
    """Create AuditLog row. Actor/ip/path resolved from thread-local request if not passed."""
    from smmsapp.models import AuditLog
    if actor is None or request is None:
        req_actor, ip, path = _get_request_meta()
        if actor is None:
            actor = req_actor
        if request is None:
            from smmsapp.middleware.audit import get_current_request
            request = get_current_request()
            if request is not None:
                _, ip2, path2 = _get_request_meta()
                ip = ip or ip2
                path = path or path2
    else:
        ip = getattr(request, 'META', {}).get('REMOTE_ADDR', '') if request else ""
        path = getattr(request, 'path', '') if request else ""

    # if after not provided but obj given, serialize current state
    if after is None and obj is not None:
        try:
            after = _serialize(obj)
        except Exception:
            after = None
    # before already serialized by caller via model_to_dict before mutation

    ct = None
    oid = None
    repr_str = ""
    if obj is not None:
        try:
            ct = ContentType.objects.get_for_model(obj.__class__)
            oid = str(obj.pk)
            repr_str = str(obj)[:255]
        except Exception:
            pass

    user_agent = ""
    if request is not None:
        try:
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:512]
        except Exception:
            pass

    try:
        AuditLog.objects.create(
            actor=actor if actor and getattr(actor, 'is_authenticated', False) else None,
            action=action,
            content_type=ct,
            object_id=oid,
            object_repr=repr_str,
            before=before,
            after=after,
            ip_address=ip if ip and ':' not in ip or ip.count(':') <= 1 else None,  # GenericIPAddressField handles v4/v6
            path=path[:512],
            user_agent=user_agent,
        )
    except Exception:
        # never break main flow
        pass

def snapshot(obj):
    try:
        return _serialize(obj)
    except Exception:
        return None
