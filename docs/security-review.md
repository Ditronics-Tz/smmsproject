# Security checks and endpoint review

## Automated checks

Pull requests and pushes run `pip-audit` against the exact pinned packages in
`requirements.txt` and Gitleaks against the checked-out repository history.
The requirements file pins the resolved runtime dependencies, so the audit is
run with `--no-deps` to avoid a second, drifting resolver pass. An audit finding
fails CI; package exceptions must be reviewed and recorded here with an owner
and removal date rather than silently ignored.

The October 2026 baseline scan found advisories in aiohttp, Brotli, CairoSVG,
Django, Django REST Framework, SimpleJWT, fonttools, idna, Markdown, Pillow,
pyasn1, PyJWT, python-dotenv, requests, sqlparse, urllib3, and WeasyPrint. Their
pins have been upgraded to pip-audit's fixed releases (Django to the supported
5.2 LTS line); rerun the committed security workflow to confirm the clean
baseline. Django 5.2 is an LTS release and supports the project's Python 3.12
runtime. See the [Django 5.2 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2/).

## Public or unauthenticated routes

The following `AllowAny` routes are intentional and reviewed:

| Route | Purpose and safeguards |
| --- | --- |
| `GET /health`, `GET /health/` | Liveness only; does not expose dependency details or user data. Subject to the anonymous API throttle. |
| `GET /api/v1/config/public` | Branding, locale, and currency only; no feature flags, secrets, or customer data. Subject to the anonymous API throttle. |
| `POST /auth/login`, `POST /api/v1/auth/login` | Credential exchange; dedicated `5/min` scoped throttle. |
| `POST /auth/forgot-password`, versioned alias | Generic response to avoid account enumeration; dedicated `3/min` scoped throttle. |
| `POST /auth/reset-password/confirm`, versioned alias | Requires a single-use expiring token; dedicated `5/min` scoped throttle. |
| `POST /auth/logout`, versioned alias | Accepts the submitted refresh token for blacklist/revocation and returns no account data; global anonymous throttle applies. |

Payment-provider callbacks are not part of this release. Do not expose a
callback endpoint without the signature, replay, timestamp, and IP controls in
the payment integration contract.

## Deployment configuration review

- `SECRET_KEY` and database password are required; there is no committed
  production fallback. `DEBUG` defaults to false.
- `ALLOWED_HOSTS` is configurable. Production must set explicit hostnames.
- CORS does not allow all origins. Configure explicit `CORS_ALLOWED_ORIGINS`
  and `CSRF_TRUSTED_ORIGINS`; credentials are enabled, so wildcard origins must
  not be introduced.
- Secure session and CSRF cookies default to HTTPS-only. TLS termination and
  HSTS need to match the production ingress configuration.
- JWT access tokens expire after 15 minutes; refresh tokens after one day,
  with rotation and blacklist-after-rotation enabled.
- Password-reset requests and confirmation are rate-limited; login and
  invitation resend have their own scopes.
- Run `python manage.py check --deploy` using the actual production settings
  and resolve environment-specific warnings before a deployment.

The local production-settings check on 2026-10-09 emitted four deployment
warnings because the active environment did not enable HSTS, HTTPS redirect,
or secure session/CSRF cookies. Set `SECURE_HSTS_SECONDS` (only after confirming
the entire domain is HTTPS), `SECURE_SSL_REDIRECT=True` when ingress supports
the configured trusted proxy header, and both secure-cookie variables to
`True`. The committed CI check supplies those production-like settings and
fails if a future configuration change introduces new deployment warnings.

## Accepted exposure and follow-up

The anonymous liveness endpoint remains accessible to load balancers. It must
stay free of database credentials, provider status, stack traces, or personal
data. The detailed `/status` route is admin-only. Security review is repeated
when a public route, authentication flow, CORS policy, or callback is changed.
