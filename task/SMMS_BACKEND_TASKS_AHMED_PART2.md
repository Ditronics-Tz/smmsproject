# SMMS Backend Tasks — Part 2 (Ahmed)

**Repo:** `smmsproject`  ·  **Owner:** Ahmed  ·  **Frontend partner:** Faraja (`smms-web`)
**Size of this file:** about 4 weeks of work. Task IDs continue from Part 1 (BE-130 onward). Faraja's Part 2 file refers to these IDs, so **do not renumber**.

This file covers: API-contract discipline, small API changes the frontend needs, per-customer feature flags, payment integrations, NFC (scan by card UID), pre-order of tomorrow's menu, sponsorship / bursary wallets, performance and security.

> **Dependency warning.** Pre-order and sponsorship post money through the ledger. Payments build on the mobile-money base. These Part 1 tasks must be **merged first**: BE-01, BE-12, **BE-22 → BE-25 (ledger core)**, BE-28, BE-29, **BE-60 (payments base)**, BE-70, **BE-80 (menu)**, BE-43. If any is late, this schedule slips — tell the team lead early.

## Rules (same as Part 1, plus these)
- Branch `BE-xx-short-name`, one task = one PR. Money code (balance, ledger, holds, funds, payments) needs **two reviewers**.
- Every new endpoint: permission test per role, AuditLog for mutations, OpenAPI serializer, error `code` from `docs/error-codes.md`.
- **Contract rule (new, see BE-130):** any PR that adds or changes an endpoint must update `docs/api-contract.md` **and** tell Faraja before merge. Response shapes in the contract at the bottom are agreed — do not change them silently.
- New business numbers go into `settings.py` with env override and a default (values in this file are the defaults).
- Everything optional is behind a feature flag (BE-131 / BE-133): `ANALYTICS, INSIGHTS, LEDGER_UI, MOBILE_MONEY, OFFLINE_POS, MENU, PREORDER, SPONSORSHIP, INTEGRATIONS, NFC_SCAN, STOCK, PARENT_LIMITS`.
- No real provider credentials in the repo or in CI. Tests use recorded fixtures or the fake provider.

## Suggested 4-week plan
- **Week 1:** BE-130, 131, 132, 133, 134 · BE-165, 166, 167 · BE-136, 144
- **Week 2:** BE-135, 137, 139, 140 · BE-145, 146 · BE-149, 150, 151
- **Week 3:** BE-152, 153, 154, 155 · BE-156, 157, 158, 159, 160 · BE-142
- **Week 4:** BE-161, 162, 163, 164 · BE-147, 148 · BE-141, 143, 138 · BE-168, 169
- Move to backlog first if behind: BE-138, 141, 143, 148, 168.

---

# A. Contract discipline and small API changes

## BE-130 — API contract protocol
**Why:** Faraja builds screens from the contract. If the backend changes without notice, screens break.

**Do this:**
1. Generate the OpenAPI schema with drf-spectacular into `docs/openapi.yaml` (`python manage.py spectacular --file docs/openapi.yaml`) and commit it.
2. CI step: regenerate the schema and fail if it differs from the committed file ("run `make schema` and commit the result"). Add `make schema` to the Makefile.
3. Create `docs/api-contract.md` (copy the contract at the bottom of this file) as the human-readable agreement. Add a PR template `.github/pull_request_template.md` with checkboxes: "Endpoint added/changed?", "`docs/api-contract.md` updated?", "Faraja informed?", "Error codes documented?".
4. Add `docs/error-codes.md` entries for all new codes in this file.
**Done when:** changing a serializer without regenerating the schema fails CI.

## BE-165 — Deposit list API: method, provider, reference, filters
**Why:** The frontend shows how each deposit was paid (FE-32).

**Do this:**
1. Add `payment_method` (`cash|mobile_money`), `provider` (null for cash), `reference` (provider reference or bank slip), `phone_masked` to the deposit list/detail serializers (mask like `+255 7** *** 123`, never return the full number to parents).
2. Filters: `payment_method`, `provider`, `status`, `from`, `to`. Pagination unchanged.
3. Old rows default to `cash`. Data migration if needed.
4. Tests: masking, filters, parent sees only own deposits.
*Depends on BE-24*

## BE-166 — User serializer additions for invites
**Why:** FE-31 needs to know if a user still has to set a password and to show the one-time invite link.

**Do this:**
1. Add read-only `password_set` (bool: `has_usable_password()`) to user list/detail serializers for admin views.
2. `create-user` response: include `invite_link` **only** when the user has no email and no mobile number; it is returned once and never stored in any log, AuditLog details or Notification.
3. `POST /auth/resend-invite` `{ user_id }` (admin): invalidates older invite tokens, creates a new one, sends by email/SMS if possible, otherwise returns `invite_link` once. Throttle 5/min per admin. AuditLog entry (without the token).
4. Tests: link is not present in any log record; permission matrix; resend invalidates the old token.
*Depends on BE-08*

## BE-167 — End-session response fields
**Why:** FE-29 shows the session summary.

**Do this:** make sure `end-session` returns `{ scanned_value, penalty_value, expected_cash, variance, status }` exactly as in the contract (values from BE-06: `scanned_value` excludes voided and penalty scans; `penalty_value` is the sum of penalty charges of the session). Include the same fields in the session detail/list endpoints. Tests for a session with normal, penalty and reversed scans.
*Depends on BE-06*

---

# B. Feature flags (per customer)

Design: each customer has its own deployment, so flags come from **two layers**: defaults from environment (`FEATURES_DEFAULT` JSON in settings) and overrides stored in the database that a superuser can change.

## BE-131 — Feature flag model and helper
**Do this:**
1. Model `FeatureFlag(key unique, enabled bool, description, updated_by null, updated_at)`.
2. Data migration seeds one row per key listed in the rules above, with the default taken from `FEATURES_DEFAULT` (env JSON; missing key = `False`, except core features which are always on and not flags).
3. Helper `smmsapp/services/features.py`: `is_enabled(key)` (reads DB, cached 60 s in Redis/local memory, cache cleared on update), `all_flags()`.
4. Unknown key → `KeyError` in code (typo protection) but `False` in the API.
5. Tests: env default vs DB override, cache invalidation.

## BE-132 — Config endpoints
**Do this:**
1. `GET /api/v1/config/public` (no auth): `{ app_name, short_name, currency: {code, symbol, decimals}, locale }`, values from settings/branding env. Never include secrets or flags here.
2. `GET /api/v1/config/features` (authenticated, any role): `{ features: { KEY: bool } }`.
3. `PUT /api/v1/config/features/{key}` `{ enabled }` (superuser only): updates the flag, AuditLog with before/after, clears cache. Returns the updated flag.
4. Permission matrix rows; unknown key → 404.
*Depends on BE-131*

## BE-133 — Enforce flags on the backend
**Why:** Hiding a menu in the frontend is not security. A disabled feature must also be closed in the API.

**Do this:**
1. Create permission class `FeatureEnabled` used like `permission_classes = [IsAdminOnly, FeatureEnabled('ANALYTICS')]` (factory pattern). When disabled → HTTP 403 with code `FEATURE_DISABLED`.
2. Apply it to: analytics, insights, ledger read API (`LEDGER_UI`), payments, menu, preorders, sponsorship, integrations, stock, parent limits, and NFC (scan with `card_uid` when `NFC_SCAN` is off returns `FEATURE_DISABLED`).
3. Celery tasks of a disabled feature must skip their work (for example `build_insights`, `build_daily_stats` for analytics can still run — decide per task and document).
4. Test: for each flag, endpoint returns 403 when off and works when on.
*Depends on BE-131*

## BE-134 — Flag management commands
**Do this:** management commands `list_features`, `set_feature KEY --on|--off`, and `apply_feature_profile <name>` where profiles (`basic`, `standard`, `full`) live in `docs/feature-profiles.json` (which flags each profile enables). Document how to choose a profile when a new customer is set up. Tests for each command.

---

# C. Payment integrations

Base already exists from BE-60 (provider abstraction, `PaymentIntent`, callback endpoint, ledger posting). These tasks harden it and add real providers.

## BE-135 — Provider research and decision document
**Do this:** write `docs/payments/providers.md` comparing at least three real options available for Tanzania (aggregators and direct mobile-money APIs). For each one record: onboarding requirements (business documents, licences), sandbox availability, authentication method, request/callback format and signature scheme, supported networks, fees, minimum/maximum amounts, settlement time, refund support, statement format for reconciliation, support quality. Finish with a recommendation table. **The owner picks the providers from this document** — do not start BE-137/138 before the decision. Also list the environment variables each provider needs.

## BE-136 — Payment state machine, events and providers list
**Do this:**
1. `PaymentIntent` allowed transitions: `pending → success|failed|expired`; `success` and `failed` are final; `expired → success` is allowed only for a **late** callback (flag `late_success=True`, still credit the wallet, notify admins).
2. New model `PaymentEvent(intent FK, type[initiated|callback|poll|credited|failed|expired|recheck], source[callback|poll|system|admin], payload JSON, external_event_id null, created_at)` with unique `(intent, external_event_id)` when present. Every callback and status check writes an event.
3. Verify amount and currency in the provider payload equal the intent; mismatch → mark `failed` with reason `AMOUNT_MISMATCH`, notify admins, do **not** credit.
4. Credit exactly once: ledger key `payment:<provider_ref>`; the deposit row and the ledger entry are created in one atomic block.
5. `GET /payments/providers` → enabled providers with `code, name, networks, min_amount, max_amount` (from settings).
6. Validate the initiate request: amount within limits (`PAYMENT_AMOUNT_OUT_OF_RANGE`), phone in valid TZ format (normalize to `+2557xxxxxxxx`/`+2556xxxxxxxx`), card belongs to the parent's child, one pending intent per card per 2 minutes.
7. Tests: every transition, late success, duplicate callback, amount mismatch.
*Depends on BE-60, BE-24*

## BE-137 — Provider adapter #1 (first chosen provider)
**Do this:**
1. New class in `smmsapp/services/payments/<provider>.py` implementing `initiate`, `verify_callback`, `get_status` from the base class.
2. Merchant reference = `PaymentIntent.id` so `initiate` is idempotent; never retry `initiate` blindly after a timeout — call `get_status` first.
3. HTTP client with timeouts (connect 5 s, read 15 s), retries only for safe calls, token caching if the provider uses OAuth, structured error mapping to our error codes (`PAYMENT_PROVIDER_UNAVAILABLE`, …).
4. Signature verification with constant-time compare (see BE-142). Secrets only from env.
5. Tests with recorded fixtures for: success, failure, timeout, pending, bad signature. **No real calls in CI.**
6. Runbook `docs/payments/<provider>-runbook.md`: how to get sandbox keys, how to register the callback URL, how to run one sandbox payment by hand, common errors.
*Depends on BE-135 decision, BE-136*

## BE-138 — Provider adapter #2
Same as BE-137 for the second provider. Only start after adapter #1 has completed a successful sandbox payment. Reuse everything from the base class; adding this adapter must not change `PaymentIntent` or the ledger code.
*Depends on BE-137*

## BE-139 — Status polling and manual recheck
**Do this:**
1. Celery Beat task every minute: for intents `pending` older than 90 seconds and younger than 15 minutes, call `get_status` and apply the result through the same state machine (writes a `poll` event). Limit to 50 intents per run; use `select_for_update(skip_locked=True)`.
2. After 15 minutes without a final status mark `expired` (`expired` event) and notify the parent.
3. `POST /payments/topup/{id}/recheck` (admin): one immediate status check, rate limited to 5/min per admin, returns the updated intent.
4. Tests with the fake provider: pending → success by poll, expiry, late success after expiry.
*Depends on BE-136*

## BE-140 — Payments admin API and status endpoint
**Do this:**
1. `GET /payments/intents` (admin) with filters `status`, `provider`, `from`, `to`, `card_number`, pagination; masked phone.
2. `GET /payments/intents/{id}` with `events: [{time, type, detail}]` (payload summarised, never raw secrets).
3. `GET /payments/status` (superuser): `{ provider, mode: "sandbox|live", callback_url, last_callback_at, pending_count }` — `mode` comes from a setting `PAYMENT_MODE` (`log` provider always reports sandbox).
4. Permission matrix rows and tests.
*Depends on BE-136*

## BE-141 — Fees and settlement posting
**Do this:**
1. Add `fee_amount` (estimate) to `PaymentIntent` (from provider response or `PAYMENT_FEE_PERCENT`).
2. Model `PaymentSettlement(provider, period_start, period_end, gross, fees, net, reference, imported_at, journal_entry null)`.
3. Ledger: new account `5100 PAYMENT_FEES` (expense). Importing a settlement posts fees: debit `5100`, credit `1100 MOBILE_MONEY_CLEARING` (key `settlement:<id>`), and the net transfer to bank: debit `1000`, credit `1100`.
4. Endpoint `POST /payments/settlements/import` (admin, CSV) with dry-run and validation of totals.
5. Tests: fee posting keeps the ledger balanced; importing the same file twice does nothing.
*Depends on BE-136, BE-22. Feeds BE-110 later.*

## BE-142 — Callback security
**Do this:**
1. Callback endpoint is `AllowAny` but **requires** a valid signature; verification in one shared function using `hmac.compare_digest`.
2. Reject payloads older than 5 minutes (timestamp tolerance) and repeated `external_event_id` (replay).
3. Optional IP allowlist setting per provider (`PAYMENT_CALLBACK_IPS`); document how to get provider IPs.
4. Support two active secrets at once so a secret can be rotated without downtime.
5. Throttle the endpoint (per IP), return quickly (do the heavy work in a Celery task if needed) and always answer with the format the provider expects.
6. Never log full payloads with personal data; log the intent id and event type only.
7. Tests: bad signature, old timestamp, replay, rotated secret.

## BE-143 — Payments reporting
**Do this:** `GET /analytics/payments?from&to` (admin, behind `ANALYTICS` and `MOBILE_MONEY` flags): per provider and per day count, amount, success rate, failed reasons, average time to confirmation, pending now. Add export (CSV/XLSX) using the existing exporter. Add rows to `DailyStats` or a new `PaymentDailyStats` (your choice, explain in the PR) so old days are fast.
*Depends on BE-136, BE-42*

## BE-144 — Development simulator for payments
**Why:** Faraja needs to test the whole top-up flow without a real provider.

**Do this:**
1. Make `LogPaymentProvider` complete: `initiate` returns pending with a fake reference.
2. `POST /payments/dev/simulate` `{ intent_id, outcome: "success|failed|delay" }` (superuser). It exists **only** when `PAYMENT_PROVIDER == "log"` or `DEBUG=True`; otherwise the route returns 404. `delay` completes the payment after 20 seconds through Celery.
3. Test that the route is not reachable with production settings.
4. Short guide `docs/payments/dev-simulator.md` for the frontend.
*Depends on BE-60*

---

# D. NFC (scan by card UID)

Context: operators will read cards with their phone. The phone gives the card's UID (a serial number), which may be formatted differently from the number our USB readers produce.

## BE-145 — Card UID field and normalization
**Do this:**
1. **Investigate first.** Collect 5 real cards. For each record: `card_number` in our database, what the USB reader outputs, and the UID a phone reads (ask Faraja for the FE-51 results). Write the findings and the mapping rule (for example byte order and decimal vs hex) in `docs/card-identifiers.md` with the real examples.
2. Add `RFIDCard.uid_hex` (CharField, unique, nullable): uppercase hex, no separators.
3. `normalize_uid(value)` in `smmsapp/services/cards.py`: strips `:`, `-`, spaces, uppercases, validates hex length (4, 7 or 10 bytes), and handles the reversed byte order if the investigation shows it is needed.
4. Management command `import_card_uids <csv>` mapping `card_number → uid_hex` with dry-run and a report of conflicts.
5. Unit tests with the real examples from the doc.
**Done when:** the doc exists and the same physical card resolves to the same `RFIDCard` with USB and with phone.

## BE-146 — Scan-card by UID
**Do this:**
1. `scan-card` accepts **either** `card_number` **or** `card_uid` — exactly one, otherwise 400 `CARD_IDENTIFIER_REQUIRED`. Normalize `card_uid` and look it up in `uid_hex`.
2. Add `scan_source` (`usb|nfc|manual`, default `usb`) to `ScannedData` and `Transaction`; return it in transaction lists (admin) and use it in analytics filters later.
3. Throttle scans per operator (setting, default 120/min) so a stuck loop on a phone cannot flood the system.
4. When `NFC_SCAN` is off, requests using `card_uid` return `FEATURE_DISABLED`.
5. Existing idempotency (`client_scan_id`, BE-70) works with UID scans too.
6. Tests: unknown UID, both identifiers sent, none sent, duplicate `client_scan_id`, throttle.
*Depends on BE-145, BE-70*

## BE-147 — Register and replace cards with a UID
**Do this:** `create-card` and `replace-card` accept optional `card_uid`. Rules: `card_uid` must be unique across `uid_hex`, and it must not equal another card's `card_number` (`CARD_UID_CONFLICT` 409). At least one of `card_number` / `card_uid` is required; if only the UID is given, generate `card_number` with the control-number service (BE-05). AuditLog records both. Tests for conflicts and replace with carry-balance.
*Depends on BE-145, BE-05*

## BE-148 — Detect cloned or impossible scans
**Why:** A UID-only card can be copied. We cannot stop copying, but we can detect it.

**Do this:** extend `build_insights` (BE-43) with `impossible_scan`: the same card scanned (a) in two different sessions of **different operators** within 2 minutes, or (b) in two sessions of **different meal types** within 10 minutes. Create an `InsightFlag` with both scan ids. Add a per-operator NFC share (`nfc_scans / total_scans`) to `/analytics/operators`. Tests with crafted data.
*Depends on BE-146, BE-43*

---

# E. Pre-order of tomorrow's menu

## Design (read before BE-149)
- A parent orders items from **tomorrow's menu** (menu = BE-80) before a **cutoff time** (`PREORDER_CUTOFF_TIME`, default 18:00 the previous day, timezone `Africa/Dar_es_Salaam`, `PREORDER_MAX_DAYS_AHEAD` default 1).
- Money is **held**, not spent: it leaves the wallet balance and sits in `2100 PREORDER_HOLD` until the meal is served (fulfilled), cancelled or missed (no-show).
- Prices are locked at order time (`unit_price` copied).
- Maximum quantity per item is `PREORDER_MAX_QTY_PER_ITEM` (default **1**, because the scan rule "same item once per session per card" still applies).
- A card with a negative balance cannot pre-order. Wallet after hold must be ≥ 0.
- Postings: place → debit `2000` (card), credit `2100` (card); fulfil → debit `2100` (card), credit `4000`; cancel/release → debit `2100` (card), credit `2000` (card).
- No-show fee `PREORDER_NOSHOW_FEE` default 0 (if > 0, taken from the hold and posted to `4100`, **no strike is added**).

## BE-149 — Pre-order models and settings
**Do this:**
1. `PreOrder(id UUID, student FK, card FK PROTECT, date, meal_type, status[placed|fulfilled|cancelled|no_show|expired], total_amount, cutoff_at, idempotency_key unique, created_by, created_at, cancelled_at null)`.
2. `PreOrderItem(preorder FK, item FK PROTECT, quantity, unit_price, fulfilled_quantity default 0)`.
3. Constraint: one **active** (`placed`) pre-order per student per `date + meal_type`.
4. Settings listed in the design; timezone-aware cutoff computation helper `cutoff_for(date)`.
5. Migration on empty and populated DB.
*Depends on BE-80*

## BE-150 — Holds in the ledger
**Do this:**
1. Add `RFIDCard.held_balance` (Decimal, default 0). Rule: `balance` excludes held money; total owned = `balance + held_balance`.
2. Seed account `2100 PREORDER_HOLD` (liability, per card via `rfid_card` on lines). Add helpers in `services/ledger.py`: `post_preorder_hold`, `post_preorder_fulfil`, `post_preorder_release` (each idempotent with keys `preorder-hold:<id>`, `preorder-fulfil:<id>:<item>`, `preorder-release:<id>`).
3. Update the nightly integrity check (BE-28): wallet lines net = `balance`; hold lines net = `held_balance`; both must match per card.
4. Card statement (BE-29) shows hold, fulfil and release lines with clear event names.
5. Tests: invariants after random sequences of place/cancel/fulfil/no-show; concurrency on the same card.
*Depends on BE-22, BE-28*

## BE-151 — Pre-order endpoints
**Do this:** implement exactly the contract (menu, create, cancel, list, summary, session):
1. `GET /preorders/menu?date&child_id`: menu for that date with `can_order`, `cutoff_at`, item prices and `max_quantity`; parent must be linked to the child.
2. `POST /preorders/create`: validates cutoff (`PREORDER_CUTOFF_PASSED`), menu exists (`PREORDER_NO_MENU`), items are on the menu, quantity limit, balance (`PREORDER_INSUFFICIENT_BALANCE`), one active order per meal type; inside one atomic block lock the card row, post the hold, create rows; idempotent by `idempotency_key` (returns the same order).
3. `POST /preorders/cancel`: only `placed`, before cutoff (`PREORDER_NOT_CANCELLABLE`), posts the release; owner or admin.
4. `GET /preorders/list`: parent sees own children's orders, admin sees all; filters status/date/child.
5. `GET /preorders/summary?date` (admin/operator): per meal type and item totals + student list (kitchen sheet).
6. `GET /preorders/session?session_id` (operator of that session or admin): expected orders for the session's meal type and date.
7. Menu protection: menu items that have active pre-orders cannot be removed (`MENU_ITEM_HAS_PREORDERS`, 409).
8. Feature flag `PREORDER`; AuditLog on create/cancel; permission matrix rows.
*Depends on BE-149, BE-150, BE-12*

## BE-152 — Fulfil pre-orders at scan
**Do this:**
1. In `scan-card`, after finding the card and active session, look for a `placed` pre-order for `today + session.meal_type`.
2. If the scanned item matches an order item with remaining quantity: fulfil one unit — post `preorder-fulfil`, reduce `held_balance`, increase `fulfilled_quantity`, create the `Transaction` as successful with `payment_breakdown = [{source: "preorder", amount}]`, **no wallet deduction and no penalty**. When all units are fulfilled the pre-order becomes `fulfilled`.
3. If the item does not match, treat as a normal scan (wallet / sponsorship rules) and leave the pre-order untouched.
4. Response adds `preorder_fulfilled: true` and `payment_breakdown`.
5. Reversal of a fulfilled pre-order transaction returns the money to the **wallet** (not back to hold) and sets the pre-order to `cancelled` with a note.
6. Tests: matching item, non-matching item, duplicate scan, reversal, concurrency with a cancel at the same time.
*Depends on BE-151, BE-25*

## BE-153 — No-show and expiry processing
**Do this:**
1. On `end-session`, mark unfulfilled `placed` pre-orders of that meal type and date as `no_show`, release the held money to the wallet (`post_preorder_release`), minus `PREORDER_NOSHOW_FEE` when > 0 (posted to `4100` with memo "pre-order no-show"). **Do not** increase `insufficient_meal_count`.
2. Nightly Celery task (23:30): any `placed` pre-order for a past date that is still open (no session took place) becomes `expired` and is released the same way.
3. Both paths are idempotent and use the release key.
4. Tests: session ended twice, fee > 0, no session that day.
*Depends on BE-150, BE-152*

## BE-154 — Pre-order notifications
**Do this:** notifications (push/email/SMS respecting existing opt-out and consent rules) for: order placed, cancelled, fulfilled, no-show (with amount returned), and optionally a reminder one hour before the cutoff for parents who have a pre-order habit (setting `PREORDER_REMINDER_ENABLED`, default off). Dedupe with `dedupe_key` (BE-10). Templates in English and Kiswahili.
*Depends on BE-151, BE-10*

## BE-155 — Pre-order test suite and edge cases
**Do this:** tests for: cutoff boundary in local time (one second before/after), balance exactly equal to the total, negative balance, cancel after cutoff, menu edit conflict, quantity > max, two simultaneous orders for the same meal type, replaced card between order and meal (order follows the student's **active** card — decide and test), reversal of fulfilled order, integrity invariants after a random sequence of 200 operations.
*Depends on BE-153*

---

# F. Sponsorship / bursary wallets

## Design (read before BE-156)
- A **fund** is money given by a sponsor to pay meals for chosen students.
- **Allocation** = which students, which meal types, optional daily/per-meal caps, valid dates, priority.
- Postings: contribution → debit `1000 BANK_CASH` (or `1100`), credit `2200 SPONSOR_FUND_LIABILITY` (line carries `fund`); meal paid by fund → debit `2200` (fund), credit `4000`; reversal → exact mirror; closing with refund → debit `2200`, credit `1000`.
- `JournalLine` gets a nullable `fund` FK. A fund balance can never go below 0.
- **Payment waterfall at scan:** (1) pre-order, (2) sponsor funds by `priority`, (3) parent wallet for the remainder.
- **Penalty rule (default, confirm with the owner):** the sponsored part stays paid; if the wallet cannot pay the remainder the normal penalty applies **to the remainder only**.
- Revenue definition changes: after BE-160, `Transaction.charged_amount` means **wallet portion only**; revenue in analytics = sum of `TransactionPayment.amount` (wallet + fund + preorder) for successful, non-voided transactions. Update BE-42 accordingly.

## BE-156 — Sponsorship models
**Do this:**
1. `SponsorFund(name, sponsor_name, contact, description, status[active|paused|closed], start_date, end_date null, alert_threshold null, created_by, created_at)`.
2. `FundContribution(fund, amount > 0, method[cash|bank|mobile_money], reference, received_at, recorded_by, journal_entry FK null)`.
3. `SponsorshipAllocation(fund, student, meal_types JSON list, daily_cap null, per_meal_cap null, valid_from, valid_to null, priority int default 100, is_active)`; unique `(fund, student)` while active.
4. `TransactionPayment(transaction FK, source[wallet|fund|preorder], fund FK null, amount, journal_entry FK)`.
5. Migrations; PROTECT on financial FKs.
*Depends on BE-22*

## BE-157 — Fund accounting in the ledger
**Do this:**
1. Add nullable `fund` FK on `JournalLine`; seed `2200 SPONSOR_FUND_LIABILITY`.
2. Helpers: `post_fund_contribution`, `post_fund_spend`, `post_fund_refund`, with idempotency keys (`fund-contrib:<id>`, `fund-spend:<txn>:<fund>`).
3. Integrity check (BE-28): for each fund, ledger net on `2200` = contributions − spend − refunds ≥ 0.
4. `GET /ledger/funds/{id}/statement?from&to&page` (admin) with running fund balance.
5. Tests: balanced entries, negative fund balance rejected, reversal restores the fund.
*Depends on BE-156, BE-28*

## BE-158 — Fund endpoints
**Do this:**
1. `GET|POST /sponsorship/funds`, `GET|PUT /sponsorship/funds/{id}` (admin, flag `SPONSORSHIP`); list shows balance, students covered, status.
2. `POST /sponsorship/funds/{id}/contribute` `{ amount, method, reference, received_at }`: posts the contribution atomically; reference required for bank/mobile money; AuditLog.
3. `POST /sponsorship/funds/{id}/close` `{ disposition: "refund"|"transfer", target_fund_id?, reason }`: refund posts to bank; transfer moves the remaining balance to another fund; the fund becomes `closed` and its allocations are deactivated.
4. `paused` funds do not pay meals.
5. Tests: contribute, close with both dispositions, permission matrix.
*Depends on BE-157*

## BE-159 — Allocation endpoints
**Do this:**
1. `POST /sponsorship/allocations` for one student; validate dates, meal types, caps (per-meal ≤ daily), fund active. Overlap with the **same fund** is `ALLOCATION_OVERLAP`; overlap with **another** fund is allowed (priority decides).
2. `POST /sponsorship/allocations/bulk` with `mode`: `class_room` (all active students of a class), `student_ids`, or `csv` (columns: student registration number, optional overrides). Always supports `dry_run`; response `{ total, valid, errors: [{row, reason}], rows[] }`; the real run is all-or-nothing per request.
3. `POST /sponsorship/allocations/{id}/deactivate`; `GET /sponsorship/allocations?fund&student&page`.
4. Add `sponsorships` to the student details response (fund name, meal types, daily cap, valid to).
5. Tests: dry-run does not write, bulk rollback, CSV with bad rows.
*Depends on BE-156*

## BE-160 — Waterfall in scan-card
**Do this:**
1. Inside the existing atomic block: lock the **card row first**, then lock fund rows ordered by `id` (avoid deadlocks).
2. Compute `remaining = item price`. Step 1: matching pre-order (BE-152). Step 2: for each eligible allocation by `priority`: fund `active`, date within `valid_from/valid_to`, meal type covered, `take = min(remaining, per_meal_cap, daily_cap_left, fund_balance)`; post `fund_spend` for `take`. Step 3: the wallet pays the rest using the current rules (penalty applies to the remainder only, see design).
3. Create `TransactionPayment` rows for every source. `Transaction.charged_amount` = wallet portion.
4. Reversal mirrors **every** payment part (fund refunded, wallet restored, pre-order handled as in BE-152). Reverse twice is impossible.
5. Update analytics (BE-42), EoD report, reconciliation (BE-06) and exports to use `TransactionPayment` for revenue, and to show sponsor-paid value separately.
6. Response adds `payment_breakdown: [{source, fund_id, fund_name, amount}]`.
7. Tests: fully sponsored, partly sponsored + wallet, cap hit, fund empty fallback, two funds by priority, penalty on the remainder, reversal, concurrent scans on the same fund.
*Depends on BE-157, BE-159, BE-152*

## BE-161 — Fund alerts and fallback
**Do this:** setting `SPONSOR_FALLBACK_TO_WALLET` (default `True`): when a fund is empty the wallet pays. Celery task hourly: fund balance ≤ `alert_threshold` → notify admins once per day (`dedupe_key`); fund empty → notify and create an `InsightFlag` (`fund_empty`). Fund whose `end_date` is in 7 days → reminder. Tests for dedupe and thresholds.
*Depends on BE-160, BE-43*

## BE-162 — Fund dashboard and sponsor report
**Do this:**
1. `GET /sponsorship/funds/{id}/dashboard?from&to`: balance, total contributed, total spent, students covered, average spend per student per day, spend by day, by meal type, by class, projected days remaining (balance ÷ average daily spend over the last 14 days; `null` if no spend).
2. `GET /sponsorship/funds/{id}/report?from&to&hide_names&format=json|csv|pdf`: totals, students covered, meals per student, per-class breakdown. With `hide_names=true` (default) use stable anonymous codes (`S-0001`, derived from the student id, same code every time) — sponsors should not see children's names by default.
3. PDF with WeasyPrint (lazy import like the EoD report), branding from settings; large ranges use the async export token flow.
4. Tests: numbers equal a direct calculation from the ledger, anonymization is stable, permission matrix.
*Depends on BE-160*

## BE-163 — Sponsorship test suite
**Do this:** randomized test: 200 random operations (contribute, allocate, scan with various combinations, reverse, pause, close) keep all invariants: journal balanced, card wallet nets, fund nets ≥ 0, `TransactionPayment` sums equal item prices. Threaded Postgres test: 20 concurrent scans on one fund never overspend it. Add both to CI.
*Depends on BE-160*

## BE-164 — Sponsorship permissions and privacy
**Do this:**
1. Add permission matrix rows for every sponsorship endpoint (admin only; parents never see other funds or sponsors; parents see only the fund **name** in their own transaction breakdown).
2. Every mutation writes an AuditLog entry; contribution and close require a reason/reference.
3. Decision (default: **no sponsor login for now**): if a read-only `sponsor` role is wanted later it needs its own task; write the proposal in `docs/sponsorship.md` (what a sponsor could see, anonymization rules, per-fund scope).
4. Document the money flows with a postings table in `docs/sponsorship.md`.
*Depends on BE-158, BE-159*

---

# G. Quality

## BE-168 — Performance test data and query tuning
**Do this:**
1. Management command `seed_load_data` (dev only, guarded by `DEBUG`): creates 2,000 students, 100k transactions over 6 months, matching journal entries, pre-orders and sponsorship data.
2. Time each analytics, ledger and insights endpoint with this data (script using Django test client or `locust`). Record p50/p95 in `docs/performance.md`.
3. Fix the worst offenders: missing indexes, N+1 queries (`assertNumQueries` tests), heavy aggregates moved to `DailyStats`. Target: list and analytics endpoints p95 under 800 ms on the seeded data.
*Depends on BE-42, BE-29*

## BE-169 — Security checklist
**Do this:**
1. Run `pip-audit` and fix or document every finding; pin exact versions in `requirements.txt`.
2. Run `python manage.py check --deploy` with production settings and fix warnings.
3. Add a secret scanner (gitleaks) to CI.
4. List every `AllowAny` endpoint (`/health`, `/status`, login, forgot-password, reset-password, callbacks, `/config/public`) and confirm each has throttling and returns no sensitive data.
5. Review CORS/CSRF settings and the JWT lifetimes; write results and changes in `docs/security-review.md`.

---

# API CONTRACT (Faraja builds against this — keep `docs/api-contract.md` identical)

All paths under `/api/v1/`. Lists: `{ count, next, previous, results }`. Amounts are decimal strings. Errors: `{ detail, code }`.

**New error codes:** `FEATURE_DISABLED`, `PAYMENT_AMOUNT_OUT_OF_RANGE`, `PAYMENT_PROVIDER_UNAVAILABLE`, `CARD_IDENTIFIER_REQUIRED`, `CARD_UID_CONFLICT`, `PREORDER_CUTOFF_PASSED`, `PREORDER_NO_MENU`, `PREORDER_INSUFFICIENT_BALANCE`, `PREORDER_NOT_CANCELLABLE`, `MENU_ITEM_HAS_PREORDERS`, `FUND_NOT_ACTIVE`, `FUND_INSUFFICIENT`, `ALLOCATION_OVERLAP`

**Config and flags**
- `GET /config/public` (no auth) → `{ app_name, short_name, currency: {code, symbol, decimals}, locale }`
- `GET /config/features` (auth) → `{ features: { "PREORDER": true, "NFC_SCAN": false, ... } }`
- `PUT /config/features/{key}` `{ enabled }` (superuser)

**Payments**
- `GET /payments/providers` → `[{ code, name, networks: ["vodacom","tigo","airtel"], min_amount, max_amount }]`
- `POST /payments/topup/initiate` `{ card_number, phone, amount, provider }` → `{ id, status }`
- `GET /payments/topup/{id}` → `{ id, status: "pending|success|failed|expired", reference, amount, new_balance }`
- `POST /payments/topup/{id}/recheck` (admin)
- `GET /payments/intents?status&provider&from&to&page` (admin); `GET /payments/intents/{id}` → adds `events: [{time, type, detail}]`
- `GET /payments/status` (superuser) → `{ provider, mode: "sandbox|live", callback_url, last_callback_at, pending_count }`
- `POST /payments/dev/simulate` `{ intent_id, outcome }` (superuser, only with the fake provider / DEBUG)
- Deposit rows add: `payment_method: "cash|mobile_money"`, `provider`, `reference`, `phone_masked`

**Session and users**
- `end-session` response adds `{ scanned_value, penalty_value, expected_cash, variance, status }`
- `create-user` response adds `invite_link` (only when no email and no mobile); user details add `password_set: bool`
- `POST /auth/resend-invite` `{ user_id }` → `{ sent: true, invite_link? }`

**NFC**
- `scan-card` body: `card_number` **or** `card_uid` (uppercase hex, no separators), plus `scan_source: "usb|nfc|manual"`, `client_scan_id`
- `create-card` and `replace-card` accept `card_uid`

**Pre-orders**
- `GET /preorders/menu?date&child_id` → `{ date, cutoff_at, can_order, meal_types: [{ meal_type, items: [{ item_id, name, price, max_quantity }] }] }`
- `POST /preorders/create` `{ child_id, date, meal_type, items: [{ item_id, quantity }], idempotency_key }` → preorder
- `POST /preorders/cancel` `{ preorder_id }`
- `GET /preorders/list?status&date&child_id&page`
- `GET /preorders/summary?date` (admin/operator) → `[{ meal_type, items: [{ item_id, name, quantity }], students: [...] }]`
- `GET /preorders/session?session_id` (operator) → preorders expected for the session
- `scan-card` response adds `payment_breakdown` and `preorder_fulfilled: bool`
- Preorder object: `{ id, child, date, meal_type, status: "placed|fulfilled|cancelled|no_show|expired", total_amount, items: [{item_id, name, quantity, unit_price}], cutoff_at }`

**Sponsorship**
- `GET|POST /sponsorship/funds`, `GET|PUT /sponsorship/funds/{id}`, `POST /sponsorship/funds/{id}/close` `{ disposition, target_fund_id?, reason }`
- `POST /sponsorship/funds/{id}/contribute` `{ amount, method, reference, received_at }`
- `GET /sponsorship/funds/{id}/dashboard?from&to`
- `GET /ledger/funds/{id}/statement?from&to&page`
- `POST /sponsorship/allocations` `{ fund_id, student_id, meal_types, daily_cap, per_meal_cap, valid_from, valid_to, priority }`
- `POST /sponsorship/allocations/bulk` `{ fund_id, mode: "class_room|student_ids|csv", ..., dry_run }` → `{ total, valid, errors, rows[] }`
- `POST /sponsorship/allocations/{id}/deactivate`, `GET /sponsorship/allocations?fund&student&page`
- `GET /sponsorship/funds/{id}/report?from&to&hide_names&format=json|csv|pdf`
- Student details add `sponsorships: [{ fund_name, meal_types, daily_cap, valid_to }]`
- Transaction rows add `payment_breakdown: [{ source: "wallet|fund|preorder", fund_id, fund_name, amount }]`
