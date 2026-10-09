# SMMS Backend Tasks — Ahmed

**Repo:** `smmsproject` (Django + DRF, PostgreSQL, Celery + Beat + Redis, SimpleJWT, drf-spectacular, WeasyPrint)
**Owner:** Ahmed
**Frontend partner:** Faraja (`smms-web`). Faraja builds against the API contract at the bottom of this file, so **do not change a response shape without telling her**.

## Rules for every task
- Branch name: `BE-xx-short-name`. One task = one PR, under ~400 changed lines where possible.
- **Money code needs two reviewers**: anything that touches `balance`, ledger, deposits, reversals, penalties.
- Every new or changed endpoint needs: a permission test per role (admin, operator, parent, student, staff, anonymous), an AuditLog entry if it mutates data, and an OpenAPI-visible serializer (`/api/docs` must show it).
- Every migration must run on an empty database **and** on a copy of real data. Never edit an old migration.
- No new hardcoded business numbers (`-500` floor, `500` penalty, `10` strikes, `1000` default threshold, `2000` sync export rows). Put them in `settings.py` with an env override and a default equal to today's value.
- Legacy paths and `/api/v1/` paths keep working (same views). New endpoints go under `/api/v1/` only.
- Run the whole suite before opening a PR: `python manage.py test smmsapp.tests`. Add tests in `smmsapp/tests/test_<area>.py`.
- File paths below come from the repo map. **Confirm the real file before editing.**
- Money is `Decimal`. Never use `float`.

## Suggested order
1. BE-01, BE-03, BE-04, BE-05, BE-06 (money safety and access control)
2. BE-02, BE-07, BE-08, BE-09, BE-11, BE-12
3. BE-20 → BE-28 (ledger core), then BE-29 → BE-31
4. BE-40 → BE-45 (analytics)
5. BE-10, BE-32
6. BE-60 → BE-122 (growth features, later)

---

# PHASE 1 — Money safety and access control

## BE-01 — Fix penalty and reversal amounts
**Why:** In `ScanRFIDCardView` (`smmsapp/views/sessions.py`) the penalty branch sets `balance = max(balance - (price + 500), -500)` but stores `Transaction.amount = price + 500`. When the floor clamps the result, the amount actually taken from the card is smaller (or zero), but reversal credits back the full stored amount. This creates money out of nothing.

**Do this:**
1. Add a field `Transaction.charged_amount` (`DecimalField`, default 0). Meaning: the amount **actually** deducted from the card.
2. In the scan view, inside the existing `transaction.atomic` + `select_for_update` block: read `balance_before`, compute `balance_after`, set `charged_amount = balance_before - balance_after` for both success and penalty. Keep `amount` as the assessed amount (price, or price + penalty fee) for reporting.
3. Write the ledger row (`LedgerEntry`) with the real delta, not the assessed amount.
4. In the reversal service (`views/wallet.py`, `transaction/reverse`): restore **`charged_amount`**, never `amount` and never a value recomputed from the item price. Reject reversal when `charged_amount` is 0 for the money part but still mark the transaction voided and handle the strike rule from BE-02.
5. Data migration: for existing rows set `charged_amount = amount` for successful transactions; for penalty transactions compute it from the matching `LedgerEntry` (`balance_before - balance_after`).
6. Add management command `report_over_credited_reversals`: lists reversals where the restored amount is greater than the original real deduction (rows created by the old bug). Output CSV: reversal id, card, expected, actual, difference. **Do not auto-fix**; the admin decides.
7. Update anything that sums `amount` for revenue (dashboard `sales-summary`, `sales-trend`, EoD PDF, exports) to use `charged_amount` for money totals.

**Tests (all required):**
- Card balance 1000, price 300 → success, charged 300, reversal restores 300.
- Card balance 100, price 300 → penalty, clamped at -500: charged = 600, reversal restores exactly 600.
- Card balance -500, price 300 → penalty, charged 0, balance stays -500, reversal restores 0 (balance still -500).
- Exact-price purchase (balance == price) → success, balance 0.
- Reversing the same transaction twice → second call rejected, balance unchanged.
- Concurrent scans (threaded, Postgres) do not double deduct.

**Done when:** all tests pass and the migration + report command run on a copy of production data.

---

## BE-02 — Strike counter rules and admin reset
**Why:** `insufficient_meal_count` blocks a card at 10 (403). Nothing defines when it goes down again, so a student can stay blocked forever.

**Default rules (use these unless the product owner says otherwise):**
- Reversing a **penalty** transaction decrements the counter by 1 (never below 0).
- A deposit does **not** reset the counter automatically. Settings flag `STRIKE_RESET_ON_DEPOSIT = False` (if `True`, a processed deposit resets to 0).
- Admin can reset manually.
- Limit is a setting `STRIKE_LIMIT = 10`; penalty fee `PENALTY_FEE = 500`; floor `RFID_BALANCE_FLOOR = -500`.

**Do this:**
1. Move the three numbers into `settings.py` (env-overridable) and replace every hardcoded use (scan view, model validators/constraint, serializers, messages).
2. Implement the decrement in the reversal service and the optional reset in deposit processing.
3. New endpoint `POST /resources/reset-strikes` `{ card_id, reason }` — admin only, sets the counter to 0, writes an AuditLog entry with before/after and the reason, returns the card.
4. Add the current `insufficient_meal_count` and `strike_limit` to the scan-card response and to card-details/student-details responses.
5. Document the rules in `docs/business-rules.md`.

**Tests:** decrement floor at 0; reversal of a non-penalty transaction does not touch the counter; reset endpoint permission matrix; deposit with the flag on and off.

---

## BE-03 — Lock down permissions
**Why:** Some endpoints are open to any logged-in user: `/list/parents|students|staffs|cards`, `CreateSchool`, `CreateItem`. A parent could list every student/parent/card or create canteen items. Also three different rules are used for "admin": `role==admin`, `is_staff`, `is_superuser`.

**Do this:**
1. `smmsapp/permissions/roles.py`: rename `IsAdminOrParent` to `IsAdminParentOrStaff` (it allows staff) and update imports. Add a short docstring to every permission class.
2. Set `IsAdminOnly` on: all `/list/*` views, `CreateSchool`, `CreateItem`.
3. Choose **one** rule for admin-only endpoints: use `role == 'admin'` (via `IsAdminOnly`). Convert `CardList`, `DeleteSchool`, `all-notifications`, audit logs and SMS logs from `IsAdminUser` (`is_staff`) to it. Keep `is_superuser` only where it means "platform owner" (school management, admin management) and document each place.
4. Check every view that has inline role checks (`StudentDetail`, `TxnList`, `ParentStudents`, deposit create) — the inline check must still deny staff/operator where intended.
5. Write `test_permission_matrix.py`: a parametrized test over **every endpoint × every role** with the expected status code in one table. A new endpoint without a row must fail a test.

**Done when:** the matrix passes, and manually as a parent you cannot call any admin-only endpoint.

---

## BE-04 — Admin without a school
**Why:** An admin with `school = null` is treated as a global admin.

**Do this:** in the create/edit user serializer require `school` for role `admin` unless the creator is a superuser and explicitly sets `is_superuser=True`. Return 400 with a clear message. Existing admins without school: write a management command that lists them; do not change them automatically. Tests for create, edit, and the list command.

---

## BE-05 — Safe control numbers
**Why:** `control_number = schoolNum + YYMM + rand4` has only 10,000 possibilities per school per month. A bulk import of a few hundred cards will collide (unique constraint error). `School.number` also wraps from 99 back to 10.

**Do this:**
1. Create `generate_control_number(school)` in one place (`smmsapp/services/`). Format: 2-digit school number + `YYMM` + 6-digit sequence.
2. Sequence per school/month from a small counter table (`ControlNumberCounter(school, yymm, last_value)`) updated with `select_for_update`. Fallback: retry loop (max 5) on `IntegrityError`.
3. Use it in `create-card`, `replace-card` and the importer.
4. `School.number`: stop wrapping. If more than 99 schools exist, raise a clear error instead of reusing a number.
5. Tests: import 1,000 cards in one run → 1,000 unique control numbers; forced collision → retry works; two concurrent creates do not collide.

---

## BE-06 — Correct session reconciliation
**Why:** `Reconciliation.scanned_value` sums `item.price` over all `ScannedData`, including voided and penalty scans, so variance is wrong.

**Do this:** compute `scanned_value` from `Transaction.charged_amount` for transactions of that session where `is_voided = False` and status is `successful`. Report penalty amounts separately in the same record (new field `penalty_value`). Update the end-session response and EoD report. Tests: session with 1 normal, 1 penalty, 1 reversed scan.

*Depends on BE-01*

---

## BE-07 — Protect financial history from cascade deletes
**Why:** `RFIDCard.student_or_staff` is `CASCADE` and `BankDeposit.control_number` is `CASCADE`. Deleting a user or card would delete money history.

**Do this:**
1. List every foreign key that points to `RFIDCard`, `Transaction`, `BankDeposit`, `LedgerEntry` (and later `JournalEntry`). Change `on_delete` to `PROTECT` on financial ones.
2. Make delete endpoints (`delete-card`, user delete/deactivate, `delete-school`) catch `ProtectedError` and return 400 with a clear message. Keep the `?force` soft-delete behaviour (`is_active=False`).
3. Migration tested on a copy of real data. Tests: deleting a user/card with history is blocked; soft-delete still works.

---

## BE-08 — Replace guessable initial passwords
**Why:** New users get `last name + 3 random chars`, which can be guessed from public information.

**Do this:**
1. On `create-user` for non-students: set an unusable password (`set_unusable_password()`), create a `PasswordResetToken` with purpose `invite` and 48-hour expiry.
2. Email (and SMS if no email but a mobile number exists) a link to the frontend `/reset-password?token=...&mode=invite`. If neither email nor mobile exists, return the one-time link in the create response **for the admin only**, shown once, never stored in a Notification.
3. Token rules stay: single use, sha256 stored, expiry, previous invite tokens invalidated on resend. Add endpoint `POST /auth/resend-invite` (admin) for expired links.
4. Remove the old password generator and any code path that emails or stores a plaintext password. Make sure the serializer redaction still passes the security tests.
5. Tests: user cannot log in before setting a password; expired token rejected; token cannot be reused; creating a user without email or mobile returns the link once.

*Coordinate with FE-02 (reset-password page).*

---

## BE-09 — Throttling behind Nginx
**Why:** Login (5/min) and forgot-password (3/min) throttles use the client IP. Behind Nginx every request may look like it comes from the proxy, so all users share one limit.

**Do this:** set `REST_FRAMEWORK["NUM_PROXIES"]` from an env variable, make sure Nginx forwards `X-Forwarded-For` and `X-Real-IP`, and make the AuditLog IP capture use the same client IP logic. Test with different `X-Forwarded-For` values. Document in `docs/deploy.md`.

---

## BE-10 — Real dedupe key for balance alerts
**Why:** Low-balance alert dedupe parses a `[student:UUID]` marker inside `Notification.message`.

**Do this:** add `Notification.dedupe_key` (nullable, indexed) with a unique constraint on `(recipient, dedupe_key)` where not null. Use key `low_balance:<student_id>:<YYYY-MM-DD>` in `services/alerts.py`. Migrate: stop reading the text marker after the migration. Tests: two sweeps on the same day create one notification per parent per child; next day creates a new one.

---

## BE-11 — Fix README and `.env.example`
**Why:** README shows `DATABASE_NAME`, `DATABASE_PASSWORD` and `ALLOWED_HOSTS=*`, but settings require `SECRET_KEY` and `DB_PASSWORD` and read `DB_NAME/DB_USER/DB_HOST/DB_PORT`; `ALLOWED_HOSTS=*` is unsafe.

**Do this:** make `.env.example` list every variable settings read (with comments: required/optional, example value), remove `ALLOWED_HOSTS=*`, update README setup steps, and fix the CI example in the README (branch `main`, `docker compose`). A new developer must be able to start the stack from the README alone — test it on a clean machine or clean clone.

---

## BE-12 — Stable error codes
**Why:** The frontend needs to translate errors to Kiswahili. Raw messages cannot be translated.

**Do this:**
1. Create `smmsapp/errors.py` with an `ErrorCode` list and a helper that returns `{ "detail": "<english text>", "code": "<CODE>" }`.
2. Apply to `scan-card`, wallet (`deposit/*`, `transaction/reverse`), `replace-card`, `end-session`. Minimum codes: `CARD_NOT_FOUND`, `CARD_INACTIVE`, `CARD_BLOCKED_STRIKES`, `SESSION_NOT_ACTIVE`, `NOT_SESSION_OPERATOR`, `DUPLICATE_ITEM_IN_SESSION`, `ITEM_INACTIVE`, `INSUFFICIENT_BALANCE_PENALTY` (returned as a success with `status: penalty`, not an error), `DEPOSIT_NOT_PENDING`, `ALREADY_REVERSED`, `DUPLICATE_CARD_NUMBER`, `DAILY_LIMIT`, `ITEM_BLOCKED`.
3. Keep HTTP status codes exactly as today.
4. Publish the code list in `docs/error-codes.md` and give it to Faraja.

---

# PHASE 2 — Double-entry (2-way) ledger

## Design (read before BE-20)
Every money movement writes a **balanced set of lines**: total debits = total credits. Rows are **append-only**. Mistakes are fixed with a reversing entry, never edited.

**Accounts (seed):**
- `1000 BANK_CASH` — asset
- `1100 MOBILE_MONEY_CLEARING` — asset
- `2000 WALLET_LIABILITY` — liability, one balance per card (lines carry `rfid_card`)
- `3000 OPENING_BALANCE` — equity
- `4000 CANTEEN_REVENUE` — income
- `4100 PENALTY_INCOME` — income
- `5900 ADJUSTMENTS` — expense

**Postings:**
- Top-up by mobile money: debit `1100`, credit `2000` (card)
- Top-up by cash/bank: debit `1000`, credit `2000` (card)
- Meal purchase: debit `2000` (card), credit `4000`
- Penalty: debit `2000` (card), credit `4100`
- Reversal: exact **mirror** of the original entry's lines
- Card replacement with balance carry: debit old card `2000`, credit new card `2000`
- Refund: debit `2000` (card), credit `1100` or `1000`
- Manual correction: `5900` against `2000`, with reason and admin

**Rules:**
1. Wallet-line amounts are the **real delta** (`balance_before - balance_after`), never the assessed price (needs BE-01).
2. Reversal = mirror of the stored lines. Never recompute from the price.
3. Every entry has a unique `idempotency_key` (`txn:<uuid>`, `deposit:<uuid>`, `reversal:<uuid>`, `payment:<provider_ref>`). Posting the same key twice returns the existing entry.
4. Entry, `RFIDCard.balance` update and source record (`Transaction`/`BankDeposit`) are saved in **one** `transaction.atomic` with the card row locked.
5. Nightly invariants: (a) all debits = all credits; (b) for each card, credits minus debits on wallet lines = `RFIDCard.balance`.
6. `JournalEntry` and `JournalLine` cannot be updated or deleted (raise in `save()` on existing rows and in `delete()`).
7. Existing cards get one `OPENING_BALANCE` entry equal to their current balance. Old `LedgerEntry` rows stay as legacy history.
8. During migration keep writing the old `LedgerEntry` too (dual-write) until BE-32.

---

## BE-20 — Ledger models and migration
Create models in `smmsapp/models.py` (or the models package):
- `LedgerAccount(code unique, name, type[asset|liability|equity|income|expense], is_active)`
- `JournalEntry(id UUID, event_type, idempotency_key unique, ref_transaction FK null, ref_deposit FK null, ref_reversal FK null, memo, created_by FK null, created_at)`
- `JournalLine(id, entry FK PROTECT, account FK PROTECT, rfid_card FK null PROTECT, direction[debit|credit], amount Decimal(14,2) > 0 via CheckConstraint, balance_after Decimal null)`
- Indexes: `(rfid_card, created_at)`, `(account, created_at)`, `(event_type, created_at)`.
- DB constraint: `amount > 0`.
Migration must run on empty and populated DB.

## BE-21 — Seed the accounts
Data migration that creates the seven accounts above. Idempotent (running twice does nothing). Test that all seven exist after `migrate`.

## BE-22 — Posting service
Create `smmsapp/services/ledger.py`:
- `post_entry(event_type, lines, idempotency_key, refs, actor, memo)` — validates: at least two lines, every amount > 0, sum(debit) == sum(credit), accounts active, wallet lines have a card and non-wallet lines do not; then saves entry + lines inside `transaction.atomic` and fills `balance_after` on wallet lines.
- Helpers built on it: `post_purchase`, `post_penalty`, `post_deposit`, `post_reversal(original_entry)`, `post_replacement`, `post_opening`, `post_adjustment`.
- Idempotency: on duplicate key return the existing entry, do not post again.
- Immutability on the models (see rule 6).
- The service must be called **inside** the caller's atomic block and must raise if the card row is not locked (check `select_for_update` was used or lock it inside).
**Tests:** unbalanced entry rejected; zero/negative amount rejected; duplicate key returns same entry; update/delete raises; reversal produces the exact mirror.

## BE-23 — Post from scan-card
In the scan view call `post_purchase` or `post_penalty` inside the existing atomic block. Every `Transaction` must have exactly one journal entry (`ref_transaction`). Keep writing `LedgerEntry`. Tests: after each scenario in BE-01, the sum of wallet lines for the card equals `RFIDCard.balance`.
*Depends on BE-01, BE-22*

## BE-24 — Post from deposits
In `deposit/process` post the deposit entry only when the action is `process`. `fail` and `pending` create no entry. A second `process` returns 409 and creates no second entry (idempotency key `deposit:<id>`). Include the account choice: `payment_method` (`mobile_money` or `cash`) decides between `1100` and `1000` (add the field to `BankDeposit`, default `cash`).
*Depends on BE-22*

## BE-25 — Post from reversals
Reversal reads the original entry's lines and posts the mirror with key `reversal:<transaction_id>`. `Reversal` + `is_voided` guards stay. Tests: reversing a clamped penalty restores exactly what was taken; reversing twice fails; the mirror entry balances.
*Depends on BE-23*

## BE-26 — Post from card replacement
In `replace-card`, when `carry_balance` is true post debit old card `2000`, credit new card `2000` for the exact old balance (negative balances included: post the mirror direction). Old card wallet becomes 0. Tests: positive balance, zero, negative.
*Depends on BE-22*

## BE-27 — Opening balances command
Management command `backfill_journal_opening [--dry-run]`: creates one `opening` entry per card with a non-zero balance (debit `3000` / credit `2000` for positive balances; mirror for negative). Idempotent (key `opening:<card_id>`). Prints a summary. Running it twice creates nothing new; the integrity check (BE-28) must pass right after.
*Depends on BE-22*

## BE-28 — Nightly integrity check
1. Service `check_ledger_integrity()` returns `{ status, checked_at, global_balanced, mismatched_cards[] }` using database aggregates (do not loop card by card in Python for large sets).
2. Celery Beat task at 02:30 daily; store the last result (model `LedgerIntegrityRun`).
3. On mismatch: create a notification for every admin and an AuditLog entry.
4. Endpoint `GET /api/v1/ledger/integrity` (admin) returns the last run; add `?run=true` to run it now.
5. Test: corrupt a card balance manually and assert the check reports it.
*Depends on BE-27*

## BE-29 — Ledger read API
Implement the contract at the bottom (journal, journal entry, card statement, account statement, trial balance).
- Pagination 50, filters `from`, `to`, `event_type`, `card_number`, `account`.
- Card statement: admin can read any card, parent only their children's cards (`ParentStudent` link), others 403.
- Use `select_related`/`prefetch_related`; no N+1 queries (add a test with `assertNumQueries`).
- Trial balance: per account total debit and total credit and net, `as_of` date.
- Everything read-only (no POST/PUT/DELETE).
*Depends on BE-22*

## BE-30 — Audit and admin for the ledger
Every manual adjustment (`post_adjustment`) requires `reason`, admin role and writes AuditLog. Register `JournalEntry`/`JournalLine`/`LedgerAccount` in Django admin as **read-only** (no add, change or delete permissions).

## BE-31 — Ledger test suite
- Randomized test: a random sequence of 200 operations (purchase, penalty, deposit, reversal, replacement) must keep both invariants after every step.
- Threaded Postgres test: 20 concurrent scans on one card never break the balance or the ledger.
- Regression test for each scenario in BE-01.
- Runs in CI (Postgres service).
*Depends on BE-25, BE-26*

## BE-32 — Retire old `LedgerEntry`
After the frontend uses the journal API: put old writes behind `LEDGER_LEGACY_WRITE=True`, switch it off, watch for one release, then remove the writes. Keep the table for history; do not drop it.
*Depends on BE-29 and the frontend statement screens*

---

# PHASE 3 — Analytics and insights (admin)

**Definitions (use these everywhere so numbers agree):**
- **Revenue** = sum of `charged_amount` of transactions with status `successful` and `is_voided = False`.
- **Penalty amount** = sum of `charged_amount` of transactions with status `penalty` and `is_voided = False`.
- **Float** = sum of `RFIDCard.balance` over active cards (matches ledger account `2000`).
- **Meal** = one non-voided transaction.

## BE-40 — Daily statistics snapshot
1. Model `DailyStats(date, meal_type, revenue, penalty_amount, meals, unique_students, deposits_amount, reversals, variance_total)` with unique `(date, meal_type)`.
2. Celery Beat task `build_daily_stats` at 01:00 for the previous day; safe to run twice (update-or-create).
3. Command `backfill_daily_stats --from --to`.
4. Test: numbers equal a direct aggregation over the same day.

## BE-41 — Indexes
Add indexes on `Transaction(transaction_date)`, `Transaction(rfid_card)`, `Transaction(session)`, `Transaction(transaction_status, is_voided)`, `ScannedData(session)`. Check with `EXPLAIN` on the analytics queries and note the results in the PR.

## BE-42 — Analytics endpoints
Create `smmsapp/views/analytics.py` and `urls/analytics.py`; admin only; read-only. Implement `sales`, `wallet-health`, `operators`, `classes`, `penalties` exactly as in the contract.
- `sales`: `group_by=day` reads `DailyStats` for past days and live data for today; `item` and `hour` use live aggregates over the range.
- `wallet-health`: float, average balance, count below each parent's effective threshold (use `_effective_threshold`), count at floor, count with strikes ≥ `STRIKE_LIMIT - 2`, deposits vs spend per day.
- `operators`: sessions, revenue, sum of variance from `Reconciliation`, count of reversals.
- Validate `from ≤ to` and a maximum range (e.g. 366 days) → 400 otherwise.
- Tests with a fixture of 30 days of data; permission matrix rows added (BE-03).
*Depends on BE-01, BE-40, BE-41*

## BE-43 — Insights endpoints
1. Model `InsightFlag(kind, reference_type, reference_id, detail JSON, status[open|resolved], created_at, resolved_by, resolved_at, note)` with unique `(kind, reference_type, reference_id)` so a resolved item does not come back.
2. Celery task `build_insights` every hour that creates flags for:
   - `reversal_spike`: operator reversals in the last 7 days above `INSIGHT_REVERSAL_LIMIT`.
   - `session_variance`: `abs(variance)` above `INSIGHT_VARIANCE_LIMIT`.
   - `duplicate_scan`: same card scanned twice within 60 seconds.
   - `deposit_stuck`: deposit still `pending` after 24 hours.
3. Endpoints (admin):
   - `GET /insights/forecast?date`: for each meal type, average meals on the same weekday over the last 4–8 weeks (at least 2 samples, else return `weeks_used: 0` and no number); round to integer.
   - `GET /insights/at-risk`: students with (a) scans this week below 50% of their 4-week weekly average, (b) 3 or more penalties in 14 days, (c) strikes ≥ `STRIKE_LIMIT - 2`. Return reasons list.
   - `GET /insights/anomalies?status=` and `POST /insights/anomalies/{id}/resolve` (`note` required, AuditLog).
   - `GET /insights/dormant-cards?days=30`: active cards without a scan in N days.
4. Thresholds live in settings.
*Depends on BE-42*

## BE-44 — Cache heavy endpoints
Cache `sales`, `wallet-health`, `operators`, `classes` for 5 minutes in Redis with a key made of the endpoint and its filters. Invalidate on `build_daily_stats`. Add a `Cache-Control: private` header. Test hit/miss.

## BE-45 — Analytics exports
Add `analytics_sales`, `analytics_wallet_health`, `analytics_operators` to the exporter (`services/exporter.py`) — CSV and XLSX, same sync (≤ 2000 rows) / async (token) behaviour, admin only.

---

# PHASE 4 — Growth features (start only when the team lead says so)

## BE-60 — Mobile-money top-up
**Do this:**
1. Provider abstraction in `smmsapp/services/payments/` like the SMS providers: `BasePaymentProvider` (`initiate`, `verify_callback`, `get_status`), `LogPaymentProvider` (fake, for development and tests), factory `get_payment_provider()` driven by `PAYMENT_PROVIDER`. Real providers (Selcom/M-Pesa/Tigo/Airtel) are added later as separate classes — the choice does not block this task.
2. Model `PaymentIntent(id, card FK, initiated_by, phone, amount, provider, provider_ref unique null, status[pending|success|failed|expired], raw_payload JSON, created_at, updated_at)`.
3. Endpoints: `POST /payments/topup/initiate` (parent, link-checked, amount ≥ `PAYMENT_MIN_AMOUNT`, normalized TZ phone), `POST /payments/callback/<provider>` (AllowAny **but** signature verified, otherwise 400), `GET /payments/topup/{id}` (owner or admin).
4. On verified success: create a processed `BankDeposit` with `payment_method='mobile_money'` and post the ledger entry with key `payment:<provider_ref>`. Duplicate callbacks are ignored. Notify the parent (push + SMS).
5. Celery task marks intents `expired` after 15 minutes without a result.
6. Store the full raw callback payload; never log secrets.
**Tests:** success, failure, duplicate callback, bad signature, amount mismatch, expired intent, permission matrix.
*Depends on BE-24*

## BE-70 — Idempotent scan endpoint (needed for offline POS)
Add `client_scan_id` (UUID, optional) to `scan-card`, stored on `ScannedData`/`Transaction` with a unique constraint `(session, client_scan_id)`. If the same id arrives again, return the **original** response with HTTP 200 and do not deduct again. Old clients without the field keep working. Tests: same id twice, same id from another session, concurrent duplicates.

## BE-80 — Daily menu
Models `DailyMenu(date, meal_type)` and `DailyMenuItem(menu, item, price_override null)`. Endpoints: admin CRUD, `POST /menu/copy` (copy a previous day), `GET /menu/today?meal_type` for operators. Setting `MENU_ENFORCED` (default False): when true, `scan-card` rejects items not on today's menu (`ITEM_NOT_ON_MENU`) and uses `price_override` when present.

## BE-90 — Parent controls
Models `SpendingRule(student, daily_limit null)` and `BlockedItem(student, item)`. Endpoints for the parent (linked children only) to read/set them. In `scan-card`, before deducting: blocked item → 403 `ITEM_BLOCKED`; today's spend + price above the limit → 403 `DAILY_LIMIT`. Tests including a limit hit exactly on the boundary.
*Depends on BE-12*

## BE-100 — Integration API for other school systems
1. Model `IntegrationKey(name, key_hash, prefix, created_by, last_used_at, revoked_at)`. Keys shown once at creation; store only the hash. Auth class `ApiKeyAuthentication` for the integration endpoints only.
2. Add `external_id` and `source_system` to `CustomUser` with a unique constraint on `(source_system, external_id)` when set.
3. Endpoints: `POST /integrations/v1/students/sync`, `/parents/sync`, `/classes/sync` — upsert by `external_id`, batch up to 500 rows, `dry_run` option, response with created/updated/failed per row. Idempotent.
4. Webhooks: model `WebhookEndpoint(url, secret, events[])`, `WebhookDelivery` log; events `meal.purchased`, `deposit.processed`, `balance.low`, `card.replaced`; HMAC-SHA256 signature header; Celery retries with backoff (up to 5), delivery log visible to admin.
5. Rate limit per key; revoke and rotate endpoints; every sync writes AuditLog.
6. Endpoints for the admin page: list/create/revoke keys, manage webhook, list sync log.
**Tests:** auth failure, revoked key, idempotent re-sync, malformed rows, signature verification helper.

## BE-101 — Adapter layer for school systems
Create `smmsapp/integrations/adapters/` with `BaseSchoolAdapter` (`fetch_students`, `fetch_parents`, `fetch_classes`) and one example adapter (CSV/HTTP JSON) selected by `SCHOOL_SYSTEM_ADAPTER`. A Celery Beat task runs the sync on the schedule from settings and reuses the same upsert code as BE-100. Adding a new school system must only require a new adapter file.
*Depends on BE-100*

## BE-110 — Three-way reconciliation
1. Models `ProviderStatementLine(provider, reference, amount, timestamp, raw)`, `ReconciliationRun(period, created_by, summary JSON)`, `ReconciliationItem(run, status[matched|missing_in_provider|missing_in_ledger|amount_mismatch], ledger_entry null, statement_line null, note, resolved_by, resolved_at)`.
2. `POST /reconciliation/upload` (admin) parses the provider CSV into statement lines (idempotent per reference).
3. Matching service: ledger deposits on account `1100` vs provider lines by reference then by amount + time window; produce items with statuses above.
4. Endpoints: run, list items with filters, resolve (note required, AuditLog).
5. Task to run automatically each night for the previous day when statement lines exist.
*Depends on BE-60*

## BE-120 — Stock control
Model `StockLevel(item OneToOne, quantity, low_threshold)` and `StockMovement(item, delta, reason, created_by)`. Scan decrements stock atomically (`select_for_update`); if `STOCK_ENFORCED` and quantity is 0, reject with `OUT_OF_STOCK`. Reversal adds stock back. Endpoints: adjust stock (admin), list. Celery task sends a low-stock notification once per day per item.

## BE-121 — Refunds
`POST /wallet/refund` (admin) `{ card_id, amount, method, reason }`: amount ≤ current balance, posts ledger (`2000` → `1100` or `1000`), notifies the parent, AuditLog, idempotent via `refund:<id>`. Tests for exceeding the balance and double submit.
*Depends on BE-22*

## BE-122 — Monthly parent statement (PDF)
Endpoint `GET /wallet/statement.pdf?child_id&from&to` (parent for own children, admin for any) using WeasyPrint (lazy import like the EoD report). Content: child, card, opening balance, list of journal lines, closing balance. Reuse the ledger read service so the numbers match the app. Limit the range to 12 months.
*Depends on BE-29*

---

# API CONTRACT (Faraja builds against this — keep it in sync)

All paths under `/api/v1/`. Lists return `{ "count": n, "next": url|null, "previous": url|null, "results": [...] }`. Amounts are decimal strings (`"600.00"`). Dates ISO 8601.

**Ledger**
- `GET /ledger/journal?from&to&event_type&card_number&account&page` (admin)
- `GET /ledger/journal/{entry_id}`
- `GET /ledger/cards/{card_id}/statement?from&to&page` (admin, or parent of that child)
- `GET /ledger/accounts/{code}/statement?from&to&page` (admin)
- `GET /ledger/trial-balance?as_of` (admin)
- `GET /ledger/integrity` (admin) → `{ status: "ok"|"mismatch", checked_at, global_balanced, mismatched_cards: [{card_id, card_number, ledger_balance, card_balance}] }`

Journal entry:
```json
{
  "id": "uuid",
  "event_type": "purchase|penalty|deposit|reversal|card_replacement|opening|adjustment",
  "memo": "string",
  "created_at": "ISO datetime",
  "ref_transaction": "uuid|null",
  "ref_deposit": "uuid|null",
  "lines": [
    {"account": "2000", "account_name": "WALLET_LIABILITY", "rfid_card": "uuid|null",
     "direction": "debit", "amount": "600.00", "balance_after": "-500.00"},
    {"account": "4100", "account_name": "PENALTY_INCOME", "rfid_card": null,
     "direction": "credit", "amount": "600.00", "balance_after": null}
  ]
}
```

**Analytics (admin)**
- `GET /analytics/sales?from&to&meal_type&group_by=day|item|hour` → `{ series: [{label, revenue, count}], totals: {revenue, count, penalty_amount} }`
- `GET /analytics/wallet-health` → `{ float_total, avg_balance, below_threshold, at_floor, near_strike_limit, deposits_vs_spend: [{date, deposits, spend}] }`
- `GET /analytics/operators?from&to` → `[{ operator_id, operator, sessions, revenue, variance_total, reversals }]`
- `GET /analytics/classes?from&to` → `[{ class_room, meals, spend, penalties }]`
- `GET /analytics/penalties?from&to` → `{ count, amount, students_near_limit: [...] }`

**Insights (admin)**
- `GET /insights/forecast?date` → `[{ meal_type, expected_meals, weeks_used }]`
- `GET /insights/at-risk` → `[{ student_id, name, class_room, reasons: ["dropped_scans"|"repeated_penalties"|"near_strike_limit"], detail }]`
- `GET /insights/anomalies?status=open|resolved` → `[{ id, kind, reference_type, reference_id, detail, status, created_at }]`
- `POST /insights/anomalies/{id}/resolve` `{ note }`
- `GET /insights/dormant-cards?days=30` → `[{ card_id, card_number, student, last_scan }]`

**Other**
- `POST /resources/reset-strikes` `{ card_id, reason }` (admin)
- `POST /payments/topup/initiate` `{ card_number, phone, amount }` → `{ id, status }`; `GET /payments/topup/{id}` → `{ id, status: "pending|success|failed|expired", reference, amount, new_balance }`
- Error body everywhere: `{ "detail": "text", "code": "ERROR_CODE" }` (BE-12)
