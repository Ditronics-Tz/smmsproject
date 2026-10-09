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

Wallet transactions retain `charged_amount` as the actual wallet delta; the session summary's `scanned_value` is the value of successful meal scans, including pre-order fulfilments, and is separate from that wallet delta.

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

`PREORDER` gates the preorder API and its scan fulfilment path. `STOCK` gates stock-management endpoints and the scheduled stock-alert task. Sponsorship and integration flags are available to clients/configuration and included in profiles, but those modules do not yet have corresponding routes. `build_insights` skips work while `INSIGHTS` is disabled. `build_daily_stats` runs regardless of `ANALYTICS` so reporting snapshots remain current; it is core aggregation work, not a feature API. `check_balance_thresholds` skips work when `PARENT_LIMITS` is disabled; notification delivery, audit cleanup, and export generation are core/background infrastructure and continue independently of feature UI flags.

## Parent spending controls (BE-90)

Parents manage controls for their linked children through `GET|PUT /api/v1/resources/parent-controls?child_id=<uuid>`. `PUT` accepts `{ child_id, daily_limit, blocked_item_ids }`; `daily_limit` may be `null` to remove the cap, and `blocked_item_ids` replaces the blocked-item list. A parent cannot read or change controls for an unlinked child. When `PARENT_LIMITS` is disabled, this endpoint returns `FEATURE_DISABLED`.

At scan time, an item in the child's blocked list returns HTTP 403 `ITEM_BLOCKED`. A purchase that would take that child's non-voided daily wallet spend above `daily_limit` returns HTTP 403 `DAILY_LIMIT`; spending exactly up to the limit is allowed. Pre-order fulfilment is not counted as new wallet spend because its funds were held when the order was placed.

## Card UID/NFC scanning

`POST /api/v1/sessions/scan-card` accepts exactly one of `card_number` or `card_uid`. UID scans require `NFC_SCAN`; send `scan_source: "nfc"` (inferred if omitted). USB scans default to `scan_source: "usb"`. Optional `client_scan_id` makes retries idempotent. Scans are rate-limited per operator using `SCAN_THROTTLE_RATE` (default 120/minute). Card UID format and the outstanding physical-card investigation are documented in `docs/card-identifiers.md`.

## Daily menu

- `GET /api/v1/menu/daily?date=YYYY-MM-DD` and `GET /api/v1/menu/daily/{id}` (admin)
- `POST /api/v1/menu/daily` and `PUT /api/v1/menu/daily/{id}` with `{ date, meal_type, items: [{ item_id, price_override? }] }` (admin)
- `DELETE /api/v1/menu/daily/{id}` and `POST /api/v1/menu/copy` with `{ source_date, target_date }` (admin)
- `GET /api/v1/menu/today?meal_type=breakfast|lunch|dinner` (operator)

Menu item `price` is the override when present, otherwise the canteen item's current price. `MENU_ENFORCED` defaults off; when enabled, scans must use an item on today's menu for the active session's meal type, and use the menu price.

## Stock control (BE-120)

`GET /api/v1/stock/` lists inventory levels. Admins adjust inventory with `POST /api/v1/stock/adjust` using `{ item_id, delta, reason, low_threshold? }`; negative resulting quantities are rejected. Meal scans decrement tracked stock under a row lock, and transaction reversal restores one unit. `STOCK_ENFORCED` defaults to false; when enabled, a scan against an empty or unconfigured stock level returns HTTP 409 `OUT_OF_STOCK`. Stock endpoints and the daily alert task are gated by `STOCK`.

## Analytics and insights (BE-40–45)

Analytics endpoints are read-only and admin-only, gated by `ANALYTICS`. Date filters use ISO dates, default to the most recent `ANALYTICS_DEFAULT_RANGE_DAYS`, and cannot exceed `ANALYTICS_MAX_RANGE_DAYS`. Sales groups by `day` (default), `item`, or `hour`; results distinguish successful revenue from penalty charges and exclude voided transactions. `/analytics/operators` retains the `{ operators: [...] }` wrapper and also reports session counts, revenue, variance, reversals, and NFC share.

`/analytics/wallet-health`, `/analytics/classes`, and `/analytics/penalties` follow the shapes in the task contract. The daily snapshot includes one row per meal type plus an `all` row; deposits and overall unique-student totals live on the `all` row to avoid counting deposits once per meal. `build_daily_stats` runs daily at 01:00 regardless of `ANALYTICS`, and can be rebuilt with `python manage.py backfill_daily_stats --from YYYY-MM-DD --to YYYY-MM-DD`.

Insights endpoints (`/insights/forecast`, `/insights/at-risk`, `/insights/anomalies`, `/insights/anomalies/{id}/resolve`, `/insights/dormant-cards`) are admin-only and gated by `INSIGHTS`. The hourly `build_insights` task skips work while that flag is disabled. An anomaly resolution is audited and remains resolved on later task runs.

## Pre-orders (BE-149–155)

Pre-orders are for a future date within `PREORDER_MAX_DAYS_AHEAD` (default 1); the default cutoff is 18:00 Africa/Dar_es_Salaam on the previous day. A successful create holds funds in `2100 PREORDER_HOLD`; serving an ordered item transfers its held value to canteen revenue. Cancellation, no-show, and expiry return unserved held funds, less the configured no-show fee where applicable. A fulfilled-order reversal restores the value to the wallet.

- `GET /api/v1/preorders/menu?date=YYYY-MM-DD&child_id=<uuid>&meal_type=lunch`
- `POST /api/v1/preorders/create` with `child_id`, `date`, `meal_type`, `idempotency_key`, and `items: [{item_id, quantity}]`
- `POST /api/v1/preorders/cancel` with `preorder_id`
- `GET /api/v1/preorders/list` (supports `status`, `date`, `child_id`, pagination)
- `GET /api/v1/preorders/summary?date=YYYY-MM-DD` (admin/operator kitchen sheet)
- `GET /api/v1/preorders/session?session_id=<uuid>` (own operator session or admin)

Parent reads are limited to linked children. `PREORDER` gates all preorder endpoints. Menu items referenced by active pre-orders cannot be removed.

If a card is replaced between ordering and the meal, the placed order follows the student: the replacement flow transfers its held balance to the new card and updates the order's protected card reference. The original card's wallet carry policy remains controlled by `carry_balance`.

## Customer feature profiles

When provisioning a customer deployment, set its `FEATURES_DEFAULT` environment JSON, run migrations, then apply a starting profile with `python manage.py apply_feature_profile basic|standard|full`. Profiles live in `docs/feature-profiles.json`; applying one sets every supported flag, overriding the environment defaults in the database. Use `basic` for menu and deposit operations, `standard` for analytics/ledger/parent limits, and `full` to enable all listed modules. Review the profile against the customer's plan before applying it; individual overrides can subsequently be changed with `python manage.py set_feature KEY --on` or `--off`. Use `python manage.py list_features` to review effective values and defaults.
