# Deployment notes

## Client IPs behind Nginx

DRF throttles and audit records resolve the client address with the same
`NUM_PROXIES` value. The default is `0`: forwarded headers are ignored, which
is safe for direct-access and local development deployments.

For one trusted Nginx edge, set `NUM_PROXIES=1` and use:

```nginx
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
```

Overwriting `X-Forwarded-For` prevents an internet client from choosing its
throttle identity. If a known load balancer precedes Nginx, configure that
upstream's trusted addresses first, preserve only the verified chain, and set
`NUM_PROXIES` to the corresponding number of entries. Do not trust forwarding
headers from a network path that can bypass those proxies.

`X-Real-IP` is forwarded for observability; Django uses `X-Forwarded-For` and
`REMOTE_ADDR` according to the proxy count, matching DRF's throttle identity.
`get_client_ip()` in `smmsapp.services.audit` uses the same rule for AuditLog.
