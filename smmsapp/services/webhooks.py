"""School webhook signing and queue helpers."""

import logging
import ipaddress
import socket
from urllib.parse import urlparse

from smmsapp.models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)


def _assert_public_https_target(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Webhook target must be an HTTPS URL without embedded credentials.")
    try:
        addresses = {record[4][0] for record in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError("Webhook hostname could not be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Webhook target must resolve only to public IP addresses.")


def dispatch_webhook_event(school_id, event, payload):
    from smmsapp.tasks import deliver_webhook
    from smmsapp.services.features import is_enabled

    if not is_enabled("INTEGRATIONS"):
        return []

    delivery_ids = []
    endpoints = WebhookEndpoint.objects.filter(school_id=school_id, is_active=True)
    for endpoint in endpoints.iterator():
        if event not in endpoint.events:
            continue
        delivery = WebhookDelivery.objects.create(endpoint=endpoint, event=event, payload=payload)
        try:
            _assert_public_https_target(endpoint.url)
            deliver_webhook.delay(str(delivery.pk))
        except ValueError as exc:
            delivery.last_error = str(exc)[:500]
            delivery.save(update_fields=["last_error"])
        except Exception:
            logger.warning("Could not queue webhook delivery id=%s event=%s", delivery.pk, event)
        delivery_ids.append(str(delivery.pk))
    return delivery_ids


def webhook_signature(secret, body):
    import hashlib
    import hmac

    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
