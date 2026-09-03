# API Versioning Policy

All endpoints are served under `/api/v1/` (versioned) and legacy unversioned paths (e.g. `/auth/login`) remain dual-served during migration with `Deprecation` header.

- Path versioning: `/api/v1/<module>/...` Examples: `/api/v1/auth/login`, `/api/v1/sessions/scan-card`.
- Additive-only within v1: new fields/endpoints added, never removed without major version bump.
- Frontend base URL: single constant `API_BASE_URL + "/api/v1"` (e.g. `service/calls.ts`).
- Sunset: legacy paths will redirect (GET) or dual-serve (POST) for one release, then 301 to `/api/v1/`.

## Health
- `GET /health` - unauthenticated liveness, no DB/Redis.
- `GET /status` - staff-only, checks DB and Redis.

Nginx/compose probes must use `/health` only.
