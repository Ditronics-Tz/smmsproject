# SMMS API developer reference

This is the handoff page for engineers who are new to the backend. Use the
running OpenAPI docs for exact request/response schemas; use the linked contract
and policy documents for behavior that is not obvious from a schema.

## Where to find the API docs

- Swagger UI: `http://localhost:8000/api/docs/`
- ReDoc: `http://localhost:8000/api/redoc/`
- OpenAPI JSON/YAML endpoint: `http://localhost:8000/api/schema/`
- Committed schema: [`openapi.yaml`](openapi.yaml)
- Human-readable frontend contract: [`api-contract.md`](api-contract.md)

The live schema and UIs are restricted to Django staff accounts (`is_staff`).
That is separate from the application's `role="admin"`; an application admin
may need the Django staff permission to open the docs. All API URLs are rooted
at the server origin.

## Make an authenticated request

Use the versioned API for new frontend or integration work. Login returns an
access token in `token` and a refresh token in `refresh`:

```powershell
$baseUrl = 'http://localhost:8000'
$loginBody = @{ username = 'your-username'; password = 'your-password' } | ConvertTo-Json
$login = Invoke-RestMethod -Method Post `
  -Uri "$baseUrl/api/v1/auth/login" `
  -ContentType 'application/json' `
  -Body $loginBody
$headers = @{ Authorization = "Bearer $($login.token)" }

Invoke-RestMethod -Method Get `
  -Uri "$baseUrl/api/v1/config/features" `
  -Headers $headers
```

Send JSON writes with `Content-Type: application/json`. Do not put tokens in
URLs, screenshots, committed fixtures, or logs.

## Route map

New application endpoints normally live under `/api/v1/`. Legacy unversioned
routes are still served for compatibility; do not add new client dependencies
on them.

| Area | Route prefix | What it covers |
| --- | --- | --- |
| Authentication | `/api/v1/auth/` | Login, token refresh, user creation, password reset and invites |
| Configuration | `/api/v1/config/` | Public branding and authenticated feature flags |
| Users, cards, menu items | `/api/v1/resources/`, `/api/v1/list/` | Resource management and role-specific lists/details |
| Sessions and scans | `/api/v1/sessions/` | Start/end sessions, card scans, transactions and scan records |
| Wallet | `/api/v1/wallet/` | Deposits, statements, ledger history and transaction reversal |
| Dashboard | `/api/v1/dashboard/` | Dashboard summaries, parent children and session details |
| Analytics and insights | `/api/v1/analytics/`, `/api/v1/insights/` | Operational reports and anomaly/forecast views |
| Menus and pre-orders | `/api/v1/menu/`, `/api/v1/preorders/` | Daily menus, ordering, fulfilment and kitchen summaries |
| Ledger | `/api/v1/ledger/` | Journal, statements, trial balance and integrity status |
| Stock and sponsorship | `/api/v1/stock/`, `/api/v1/sponsorship/` | Inventory and sponsor-fund operations |
| Imports and exports | `/api/v1/imports/`, `/api/v1/exports/` | Bulk data and report exports |
| School integrations | `/integrations/v1/` | API-key-authenticated student/parent/class sync and admin integration tools |

Operational endpoints outside the API prefix include `/health` (liveness) and
`/status` (restricted status details). Do not use `/status` as a public health
probe.

## Response conventions

- Paginated lists use `{ count, next, previous, results }`; the default page
  size is 5. Follow `next` rather than assuming the whole list fits on one page.
- Amounts are decimal strings. Keep them as decimal values; do not parse money
  through binary floating point.
- Stable API errors use `{ detail, code }`. Client behavior should branch on
  `code`, not English text. Some older auth/resource handlers still expose
  integer codes and `message`; check the endpoint schema and
  [`error-codes.md`](error-codes.md) before relying on an error shape.
- Mutating endpoints may require a reason, reference, idempotency key, or audit
  context. Do not retry a non-idempotent write blindly.
- Feature-gated routes return HTTP 403 with `FEATURE_DISABLED` when disabled.

## Permissions and privacy

The application's role values are `admin`, `operator`, `parent`, `student`,
and `staff`. They are not interchangeable with Django's `is_staff` or
`is_superuser` flags. Check [`permission-matrix.md`](permission-matrix.md) and
the endpoint's `permissions` section in OpenAPI before implementing a client.

Parents are scoped to their linked children. Never assume that knowing a UUID
grants access. Deposit responses expose only `phone_masked`; never display or
log a full parent phone number. Invite tokens and credentials are secrets.

For NFC, scan requests send exactly one of `card_number` or `card_uid`; see
[`card-identifiers.md`](card-identifiers.md) for the current normalization rule
and the outstanding physical-card verification.

## Useful contract references

- [`api-contract.md`](api-contract.md): session summaries, invites, flags,
  menus, pre-orders, NFC and other frontend-facing response behavior.
- [`error-codes.md`](error-codes.md): stable error identifiers and HTTP status.
- [`permission-matrix.md`](permission-matrix.md): role access and integration
  authentication.
- [`feature-profiles.json`](feature-profiles.json): deployment flag profiles.
- [`security-review.md`](security-review.md): public endpoints and security
  checks. CI workflows are currently disabled; checks must be run manually.

## When changing an endpoint

1. Update its serializer/view and add tests for success, validation, and every
   affected role.
2. Update `docs/api-contract.md` and `docs/error-codes.md` if the contract or
   errors change. For a client-visible change, coordinate with the frontend
   owner before release.
3. Regenerate and inspect the schema:

   ```powershell
   make schema
   git diff -- docs/openapi.yaml
   ```

4. Run relevant tests, then the full suite before release:

   ```powershell
   python manage.py test smmsapp.tests
   ```

   The repository currently has no CI/CD workflows, so schema drift, tests,
   dependency audits and secret scans will not run automatically on a PR.

