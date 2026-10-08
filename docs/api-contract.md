# API contract

This document records the backend agreement for the frontend and API changes in BE-130, BE-165, and BE-166. The versioned endpoints are served under `/api/v1/`; legacy unversioned routes remain available during migration.

## Deposit list and detail

`GET /api/v1/wallet/deposit/list` returns paginated deposits. Pagination keeps the existing response shape and page size.

Each deposit includes:

- `payment_method`: `cash` or `mobile_money`. Existing records are treated as `cash`.
- `provider`: `null` for cash; the mobile money provider for mobile money payments.
- `reference`: provider reference or bank slip reference, or `null` when absent.
- `phone_masked`: the submitter's masked phone number, such as `+255 7** *** 123`. The full number is never returned by deposit responses.

The list accepts `payment_method`, `provider`, `status`, `from`, and `to` query parameters. `from` and `to` are inclusive dates in `YYYY-MM-DD` format. Administrators and operators can list all deposits; parents can list only deposits they submitted.

Deposit creation accepts the same payment details. Cash deposits must have a null provider. Mobile money deposits require a provider.

## User password state and invites

Admin user list and detail responses include read-only `password_set`, which is true only when the user has a usable password.

Creating a user issues a single-use password-setting invite. The invite is sent by email when an email address is present, otherwise by SMS when a mobile number is present. The create response includes `invite_link` only when neither contact method is available. The raw invite token is never stored in notifications, audit details, or SMS log records.

`POST /api/v1/auth/resend-invite` accepts `{ "user_id": "<UUID>" }` and is restricted to administrators. It invalidates previous unused password reset/invite tokens, issues a new token, and sends the invite by email or SMS when possible. If the user has neither contact method, the response includes `invite_link` once. Requests are limited to five per minute per administrator.

The invite link opens `/auth/accept-invite` with its one-time token in the URL fragment. The page submits the token to `POST /api/v1/auth/reset-password/confirm` with `{ "token": "<token>", "new_password": "<password>" }`. The token is single-use and expires after 30 minutes. Keeping it in the fragment prevents it from being sent in the initial HTTP request URL.

## Error responses

Errors use the existing numeric `code` and human-readable `message` response fields. Documented codes and meanings are listed in [error-codes.md](error-codes.md). Throttled requests return HTTP 429.

## Session close summary

`POST /api/v1/sessions/end-session` returns exactly these fields: `scanned_value`, `penalty_value`, `expected_cash`, `variance`, and `status`. `scanned_value` sums successful, non-voided meal scans and excludes penalty and reversed scans. `penalty_value` sums only the penalty charge (the transaction amount less the meal price) for non-voided penalty scans. `variance` is `expected_cash - scanned_value`; `status` is `matched` or `variance`.

Session list responses and the operator's `/api/v1/dashboard/last-session` detail also carry these summary values. The session list's `status` is the reconciliation status; `session_status` retains the lifecycle state (`active`, `completed`, or `cancelled`).

## Deployment config and feature flags

`GET /api/v1/config/public` is unauthenticated and returns branding, currency, and locale only. It never returns secrets or feature flag values.

`FEATURES_DEFAULT` is a JSON object of supported feature keys to boolean deployment defaults. Missing database rows fall back to the environment value (or false). `GET /api/v1/config/features` requires authentication and returns `{ "features": { "KEY": true } }`. `PUT /api/v1/config/features/{key}` is superuser-only, accepts `{ "enabled": boolean }`, and returns the updated flag. Unknown keys return 404. Feature values are cached for up to 60 seconds and model updates invalidate the cache.

## Backend feature enforcement

Feature-gated APIs return HTTP 403 with code `FEATURE_DISABLED` when the database override (or environment default) is off. Current gates are:

- `ANALYTICS`: dashboard counts, sales summary/trend, and end-of-day report.
- `LEDGER_UI`: card ledger reads.
- `PAYMENTS`: deposit create/list/process and transaction reversal.
- `MENU`: canteen item list/create/edit/delete endpoints, including `/list/canteen-items`.
- `PARENT_LIMITS`: parent balance-threshold API and its scheduled low-balance sweep.
- `NFC_SCAN`: scan requests that supply `card_uid`. Existing USB/RFID requests using `card_number` remain available regardless of this flag. NFC UIDs are normalized to uppercase hexadecimal and matched against `RFIDCard.uid_hex`.

The current backend has no preorder, sponsorship, integration, or stock endpoints. Their flags are available to clients/configuration and are included in profiles, but there is no corresponding route to gate yet. `build_insights` skips work while `INSIGHTS` is disabled. There is no `build_daily_stats` task in this codebase. `check_balance_thresholds` skips work when `PARENT_LIMITS` is disabled; notification delivery, audit cleanup, and export generation are core/background infrastructure and continue independently of feature UI flags.

## Card UID/NFC scanning

`POST /api/v1/sessions/scan-card` accepts exactly one of `card_number` or `card_uid`. UID scans require `NFC_SCAN`; send `scan_source: "nfc"` (inferred if omitted). USB scans default to `scan_source: "usb"`. Optional `client_scan_id` makes retries idempotent. Scans are rate-limited per operator using `SCAN_THROTTLE_RATE` (default 120/minute). Card UID format and the outstanding physical-card investigation are documented in `docs/card-identifiers.md`.

## Customer feature profiles

When provisioning a customer deployment, set its `FEATURES_DEFAULT` environment JSON, run migrations, then apply a starting profile with `python manage.py apply_feature_profile basic|standard|full`. Profiles live in `docs/feature-profiles.json`; applying one sets every supported flag, overriding the environment defaults in the database. Use `basic` for menu and deposit operations, `standard` for analytics/ledger/parent limits, and `full` to enable all listed modules. Review the profile against the customer's plan before applying it; individual overrides can subsequently be changed with `python manage.py set_feature KEY --on` or `--off`. Use `python manage.py list_features` to review effective values and defaults.
