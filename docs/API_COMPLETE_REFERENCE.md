# SMMS API reference (complete client handoff)

This document is a self-contained, human-readable reference for the API routes
registered by this repository. It describes the JSON shapes that clients send
and receive; a consumer should not need to open Swagger, fetch an OpenAPI file,
or infer fields from source code to integrate an endpoint. It is based on the
current URL configuration, views, serializers, and the human-readable contract.

If code changes an endpoint, update this document in the same change. Amounts
are decimal values (normally serialized as strings in model serializers); send
and parse them as decimals, never binary floating point. Timestamps are ISO-8601
with timezone. UUIDs are strings. Dates use `YYYY-MM-DD`.

## Base URL, authentication, and common behavior

- New clients should use `/api/v1/`. The school-system integration API uses
  `/integrations/v1/` and API keys, not user bearer tokens.
- Authenticated endpoints use `Authorization: Bearer <token>` (login returns
  the access value under `token`; token refresh returns `access`).
- App roles are `admin`, `operator`, `parent`, `student`, and `staff`. A Django
  `is_staff` account is distinct from app role `admin`; `is_superuser` is a
  separate privilege used for feature configuration.
- Parent records and deposits are scoped to the authenticated parent's linked
  children; knowing another child's UUID does not grant access.
- Generic DRF pagination uses `{count,next,previous,results}` and the global
  default page size (5 unless an endpoint says otherwise). Card ledger uses
  50/page, supports `page_size`, maximum 200. Preorder list uses
  `{count,results}`, default 50 and maximum 100. Some list endpoints are
  unpaginated arrays; each is called out below.
- Stable errors commonly use `{code,detail}`. Older auth/resource handlers
  may return `{code,message}` or field errors. A feature-disabled endpoint
  returns HTTP 403 `{code:"FEATURE_DISABLED",feature:"<KEY>"}`. See
  [`error-codes.md`](error-codes.md) for stable codes.

## Shared JSON objects

### User and school

```json
{
  "id": "uuid",
  "first_name": "Asha",
  "middle_name": "",
  "last_name": "Musa",
  "username": "asha.musa",
  "email": "asha@example.test",
  "mobile_number": "+255712345678",
  "role": "parent",
  "gender": "female",
  "parent_type": "mother",
  "class_room": null,
  "school": {"id": 1, "name": "Example School", "location": "Dar es Salaam", "number": "SCH-1"},
  "profile_picture": null,
  "is_active": true,
  "date_joined": "2026-01-01T09:00:00+03:00",
  "password_set": true
}
```

Fields may be omitted for role-specific compact serializers. `password_set` is
read-only and only tells whether a usable password exists. Never return or log
passwords or invite tokens beyond the one-time invite response.

Compact list serializers used by `/api/v1/list/*` have these exact row shapes:

```json
{
  "school": {"id": 1, "name": "Example School", "location": "Dar es Salaam", "number": "SCH-1"},
  "student": {"id": "uuid", "first_name": "Asha", "middle_name": "", "last_name": "Musa", "gender": "female", "class_room": "P1", "school": "Example School", "profile_picture": null},
  "parent": {"id": "uuid", "first_name": "Neema", "last_name": "Musa", "parent_type": "mother", "email": "neema@example.test", "mobile_number": "+255712345678", "gender": "female"},
  "staff": {"id": "uuid", "first_name": "Juma", "middle_name": "", "last_name": "Musa", "gender": "male", "school": "Example School"},
  "canteen_item": {"id": "uuid", "name": "Rice", "price": "2500.00", "is_active": true, "created_at": "...", "updated_at": "..."}
}
```

`/list/cards` rows use the Card shape below; `/list/students`, `/parents`,
`/staffs`, `/schools`, and `/canteen-items` return arrays of the corresponding
objects above. These list endpoints are unpaginated. Resource search-list
endpoints use the generic paginated envelope and a page size of 50.

### Card, transaction, and session

```json
{
  "card": {
    "id": "uuid", "balance": "12000.00", "held_balance": "0.00",
    "is_active": true, "control_number": "12345678901",
    "card_number": "00012345", "uid_hex": "04A1B2C3D4E5F6",
    "issued_date": "2026-01-01", "insufficient_meal_count": 0,
    "strike_limit": 10, "created_at": "2026-01-01T09:00:00+03:00"
  },
  "transaction": {
    "id": "uuid", "amount": "2500.00", "charged_amount": "2500.00",
    "student_name": "Asha Musa", "card_number": "00012345",
    "item_name": "Lunch", "transaction_date": "2026-01-01T12:00:00+03:00",
    "transaction_status": "successful", "scan_source": "usb",
    "payment_breakdown": [{"source": "wallet", "fund_name": null, "amount": "2500.00"}]
  },
  "session": {
    "id": "uuid", "operator": "uuid", "type": "lunch", "status": "active",
    "session_status": "active", "start_at": "2026-01-01T11:00:00+03:00",
    "end_at": null, "scanned_value": "2500.00", "penalty_value": "0.00",
    "expected_cash": "0.00", "variance": "0.00"
  }
}
```

Session `type` is `breakfast|lunch|dinner`; status is `active|completed` in the
application. `scanned_value` excludes voided transactions and penalty scans;
`penalty_value` is the session penalty-charge total. End-session returns
exactly `scanned_value`, `penalty_value`, `expected_cash`, `variance`, `status`.
Scan source is `usb|nfc|manual`. NFC scans use `card_uid` and require the
`NFC_SCAN` feature.

### Standard pagination and error examples

```json
{"count": 24, "next": "?page=2", "previous": null, "results": []}
```

```json
{"code": "FEATURE_DISABLED", "feature": "PREORDER"}
```

## Configuration

| Method and path | Access | Query/body | Success response |
| --- | --- | --- | --- |
| `GET /api/v1/config/public` | Public | None | `{ "app_name":"SMMS", "short_name":"SMMS", "currency":{"code":"TZS","symbol":"TSh","decimals":2}, "locale":"en-TZ" }` (values are deployment settings) |
| `GET /api/v1/config/features` | Any authenticated role | None | `{ "features": { "ANALYTICS": true, "PREORDER": false } }` (includes configured flags; no secrets) |
| `PUT /api/v1/config/features/{key}` | Authenticated superuser | `{ "enabled": true }` | `{ "key":"PREORDER", "enabled":true, "description":"...", "updated_by":"uuid", "updated_at":"..." }`; unknown key 404 |

## Authentication and account lifecycle

All paths below are also available under legacy `/auth/` without the `api/v1`
segment. Prefer the versioned paths.

| Method and path | Access | Request | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/auth/login` | Public; throttled | `{ "username":"username, email, or mobile", "password":"..." }` | `{ "refresh":"...", "token":"...", "user":{"id":"uuid","username":"...","email":"...","mobile_number":"...","role":"parent","profile_picture":null,"first_name":"...","middle_name":"...","last_name":"...","is_superuser":false,"school":{"id":1,"name":"...","location":"...","number":"..."}} }` |
| `POST /api/v1/auth/token/refresh` | Public with refresh token | `{ "refresh":"..." }` | `{ "access":"..." }` (SimpleJWT response) |
| `POST /api/v1/auth/logout` | Authenticated | `{ "refresh":"..." }` | `{ "message":"Successfully logged out." }` |
| `POST /api/v1/auth/create-user` | Admin | User create fields below | `{ "message":"...", "user":{...user object...}, "invite_link":"https://..." }`; `invite_link` is included only if no email and no mobile number are on the user |
| `POST /api/v1/auth/resend-invite` | Admin; 5/min/admin | `{ "user_id":"uuid" }` | `{ "message":"...", "invite_link":"https://..." }`; link returned only if there is no deliverable email/mobile; never stored in logs/audit/notifications |
| `GET /api/v1/auth/accept-invite#token={token}` | Public HTML/browser flow | The token is in the URL fragment (browser-only; not sent to the server in the initial GET) | HTML password setup page; the page submits `{ "token":"...", "new_password":"..." }` to `POST /api/v1/auth/reset-password/confirm`. That confirm endpoint accepts invite tokens as well as reset tokens. |
| `POST /api/v1/auth/edit-user` | Admin | `{ "user_id":"uuid", ...editable user fields... }` | `{ "message":"User updated successfully", "user":{...user serializer fields...} }` |
| `POST /api/v1/auth/activate-deactivate-user` | Admin | `{ "user_id":"uuid", "is_active":true }` | `{ "message":"..." }` |
| `POST /api/v1/auth/forgot-password` | Public; throttled | `{ "email":"person@example.test" }` | Generic `{ "message":"If the account exists, reset instructions will be sent." }` |
| `POST /api/v1/auth/reset-password/confirm` | Public; throttled | `{ "token":"...", "new_password":"..." }` | `{ "message":"Password has been reset." }` |
| `POST /api/v1/auth/change-password` | Authenticated | `{ "old_password":"...", "new_password":"..." }` | `{ "message":"Password changed successfully." }` |

User-create accepted fields (requiredness depends on role and server validation):

```json
{
  "first_name":"Asha", "middle_name":"", "last_name":"Musa",
  "username":"asha.musa", "email":"asha@example.test",
  "mobile_number":"+255712345678", "role":"parent", "school":1,
  "class_room":null, "gender":"female", "password":"optional initial password",
  "profile_picture":null, "parent_type":"mother", "parent_ids":[],
  "student_ids":["student-uuid"], "is_superuser":false
}
```

For students, parent IDs establish parent links and username may be generated;
for parents, student IDs establish child links. Never assume every field applies
to every role.

## Dashboard

The dashboard endpoints use POST bodies for compatibility with the existing
client. Legacy aliases are under `/dashboard/`.

| Method and path | Access | Request | Success response shape |
| --- | --- | --- | --- |
| `POST /api/v1/dashboard/counts` | Admin/operator; `ANALYTICS` | `{}` | `{ "total_students":0,"total_parents":0,"total_staffs":0,"total_available_balance":"0.00","total_transactions":0,"sessions":0,"price_week":0,"price_today":0 }` |
| `POST /api/v1/dashboard/sales-summary` | Admin; `ANALYTICS`; `{ "filter":"day" }` (`day|month|year`) | `{ "total_success_amount":"0.00","total_penalts_amount":"0.00","total_success":0,"total_penalts":0,"filter_type":"day" }` |
| `POST /api/v1/dashboard/sales-trend` | Admin; `ANALYTICS`; `{}` | Array `[{"date":"YYYY-MM-DD","sales_amount":"0.00"}]` for the latest seven days with sales |
| `GET /api/v1/dashboard/end-of-day-report` | Admin or parent; `ANALYTICS` | PDF attachment `SMMS_Day_report.pdf`, not JSON; other roles are forbidden |
| `POST /api/v1/dashboard/parent-students` | Parent; `{}` | Array of full student objects including card, parents, latest transactions and sponsorships |
| `POST /api/v1/dashboard/children-spend` | Parent; `{ "period":"week", "child_id":"uuid" }` (`period=week|month`, child_id optional) | `{ "period":"week","start_date":"YYYY-MM-DD","children":[{"child_id":"uuid","child_name":"...","class_room":"...","total_spend":"0.00","transaction_count":0,"penalty_amount":"0.00","items":[{"item_id":"uuid","item_name":"...","quantity":0,"amount":"0.00"}]}] }`; only linked children |
| `POST /api/v1/dashboard/staff-view` | Staff; `{}` | Full staff object with active card, latest transactions and `password_set` |
| `POST /api/v1/dashboard/last-session` | Operator; `{}` | `{ "session_id":"uuid","session_type":"lunch","session_status":"completed","start_time":"...","end_time":"...","total_price":"0.00","student_count":0,"scanned_value":"0.00","penalty_value":"0.00","expected_cash":"0.00","variance":"0.00","status":"matched" }` |
| `GET /api/v1/dashboard/balance-threshold` | Parent; `PARENT_LIMITS` | `{ "balance_threshold":"5000.00", "effective_threshold":"5000.00" }` |
| `PUT /api/v1/dashboard/balance-threshold` | Parent; `PARENT_LIMITS`; `{ "balance_threshold":"5000.00" }` (null resets to default) | Same threshold object |
| `GET /api/v1/resources/parent-controls?child_id=uuid` | Parent; `PARENT_LIMITS` | `{ "child_id":"uuid", "daily_limit":"10000.00", "blocked_item_ids":["uuid"] }` |
| `PUT /api/v1/resources/parent-controls` | Parent; `PARENT_LIMITS`; `{ "child_id":"uuid", "daily_limit":"10000.00", "blocked_item_ids":["uuid"] }` | Same controls object |

## Analytics and insights

Analytics requires `ANALYTICS`; insights require `INSIGHTS`. Analytics routes
are admin-only. `from` and `to` are optional ISO dates where supported; omitted
range uses the configured default range.

| Method and path | Query/body | Response |
| --- | --- | --- |
| `GET /api/v1/analytics/sales?from=YYYY-MM-DD&to=YYYY-MM-DD&group_by=day` | `group_by`: `day|item|hour` | `{ "series":[{"label":"...","revenue":"0.00","count":0,"penalty_amount":"0.00"}], "totals":{"revenue":"0.00","count":0,"penalty_amount":"0.00"} }` |
| `GET /api/v1/analytics/wallet-health` | None | `{ "float_total":"0.00", "avg_balance":"0.00", "below_threshold":0, "at_floor":0, "near_strike_limit":0, "deposits_vs_spend":[{"date":"YYYY-MM-DD","deposits":"0.00","spend":"0.00"}] }` |
| `GET /api/v1/analytics/operators?from=&to=` | Date range | `{ "operators":[{"operator_id":"uuid","operator":"Name","sessions":0,"revenue":"0.00","variance_total":"0.00","reversals":0,"nfc_scans":0,"total_scans":0,"nfc_share":0.0}] }` |
| `GET /api/v1/analytics/classes?from=&to=` | Date range | `[{"class_room":"P1","meals":0,"spend":"0.00","penalties":"0.00"}]` |
| `GET /api/v1/analytics/penalties?from=&to=` | Date range | `{ "count":0, "amount":"0.00", "students_near_limit":[{"student_id":"uuid","name":"...","class_room":"...","insufficient_meal_count":0}] }` |
| `GET /api/v1/insights/forecast?date=YYYY-MM-DD` | Date optional (today default) | `[{"meal_type":"lunch","expected_meals":0,"weeks_used":8}]`; expected may be null when insufficient history |
| `GET /api/v1/insights/at-risk` | None | `[{"student_id":"uuid","name":"...","class_room":"...","reasons":["dropped_scans"],"detail":{"scans_this_week":0}}]` |
| `GET /api/v1/insights/anomalies?status=open` | `status=open|resolved` | `[{"id":"uuid","kind":"...","reference_type":"...","reference_id":"...","detail":{},"status":"open","created_at":"..."}]` |
| `POST /api/v1/insights/anomalies/{flag_id}/resolve` | `{ "note":"Reviewed and corrected." }` | `{ "id":"uuid", "status":"resolved", "note":"...", "resolved_at":"..." }` |
| `GET /api/v1/insights/dormant-cards?days=30` | `days` 1–365 | `[{"card_id":"uuid","card_number":"...","student":"...","last_scan":null}]` |

## Menus and pre-orders

Menu mutations require the menu management permission and `MENU` feature;
preorder endpoints require `PREORDER`. Menu meal types are breakfast, lunch,
and dinner.

| Method and path | Access / request | Response |
| --- | --- | --- |
| `GET /api/v1/menu/daily?date=YYYY-MM-DD` | Admin | Array of menu objects `{id,date,meal_type,items:[{item_id,name,price,price_override}],created_at}`; `meal_type` is not a list filter |
| `POST /api/v1/menu/daily` | Admin; `{ "date":"YYYY-MM-DD", "meal_type":"lunch", "items":[{"item_id":"uuid","price_override":null}] }` | Created menu object `{id,date,meal_type,items:[...],created_at}` |
| `GET /api/v1/menu/daily/{menu_id}` | Admin/operator | One menu object |
| `PUT /api/v1/menu/daily/{menu_id}` | Admin/operator; same JSON as create | Updated menu object |
| `DELETE /api/v1/menu/daily/{menu_id}` | Admin/operator | `{ "message":"..." }`; active preorders can prevent removal (`MENU_ITEM_HAS_PREORDERS`) |
| `POST /api/v1/menu/copy` | Admin; `{ "source_date":"YYYY-MM-DD", "target_date":"YYYY-MM-DD" }` | HTTP 201 array of copied menu objects |
| `GET /api/v1/menu/today?meal_type=lunch` | Operator | One current-day menu object; `meal_type` is required |
| `GET /api/v1/preorders/menu?date=YYYY-MM-DD&child_id=uuid&meal_type=lunch` | Parent (linked child) or admin | `{ "date":"YYYY-MM-DD", "meal_type":"lunch", "can_order":true, "cutoff_at":"...", "items":[{"item_id":"uuid","name":"...","price":"2500.00","max_quantity":1}] }` |
| `POST /api/v1/preorders/create` | Parent; create body below | HTTP 201 order; same idempotency key returns existing order with HTTP 200 |
| `POST /api/v1/preorders/cancel` | Owner parent or admin; `{ "preorder_id":"uuid" }` | PreOrder object below |
| `GET /api/v1/preorders/list?status=placed&date=YYYY-MM-DD&child_id=uuid&page=1&page_size=50` | Parent (own children) or admin | `{ "count":1,"results":[PreOrder] }` |
| `GET /api/v1/preorders/summary?date=YYYY-MM-DD` | Admin/operator | `{ "date":"YYYY-MM-DD", "meals":{"lunch":{"items":{"item-uuid":{"name":"Rice","quantity":3}},"students":[{"student_id":"uuid","name":"...","items":[{"name":"Rice","quantity":1}]}]}} }` |
| `GET /api/v1/preorders/session?session_id=uuid` | Session operator or admin | Array of PreOrder objects expected for that session's meal/date |

Create request:

```json
{
  "child_id":"student-uuid", "date":"2026-10-11", "meal_type":"lunch",
  "idempotency_key":"client-generated-unique-key",
  "items":[{"item_id":"item-uuid","quantity":1}]
}
```

PreOrder response:

```json
{
  "id":"uuid", "student":"uuid", "student_name":"Asha Musa",
  "card":"uuid", "card_number":"00012345", "date":"2026-10-11",
  "meal_type":"lunch", "status":"placed", "total_amount":"2500.00",
  "cutoff_at":"2026-10-10T18:00:00+03:00",
  "items":[{"item":"uuid","item_name":"Rice","quantity":1,"unit_price":"2500.00","fulfilled_quantity":0}],
  "created_at":"...", "cancelled_at":null, "note":""
}
```

Status values are `placed|fulfilled|cancelled|no_show|expired`. The held amount
is not spent until fulfilment; reversal of a fulfilled meal refunds the wallet.

## Stock and sponsorship

Stock requires the `STOCK` feature. Sponsorship requires `SPONSORSHIP`.

| Method and path | Access / body or query | Response |
| --- | --- | --- |
| `GET /api/v1/stock/` | Admin/operator | `[{"item_id":"uuid","item_name":"Rice","quantity":20,"low_threshold":5,"updated_at":"..."}]` |
| `POST /api/v1/stock/adjust` | Admin; `{ "item_id":"uuid", "delta":-2, "reason":"Wastage", "low_threshold":5 }` | Stock level object plus adjustment result |
| `GET /api/v1/sponsorship/funds` | Admin | Array of SponsorFund objects |
| `POST /api/v1/sponsorship/funds` | Admin; `{ "name":"Fund A", "sponsor_name":"Sponsor", "contact":"...", "description":"...", "status":"active", "start_date":"YYYY-MM-DD", "end_date":"YYYY-MM-DD", "alert_threshold":"10000.00" }` | Fund object |
| `GET /api/v1/sponsorship/funds/{fund_id}` | Admin | Fund object |
| `PUT /api/v1/sponsorship/funds/{fund_id}` | Admin; editable fund fields | Fund object |
| `POST /api/v1/sponsorship/funds/{fund_id}/contribute` | Admin; `{ "amount":"10000.00", "method":"cash", "reference":"receipt/ref" }` | `{id,amount,method,reference,received_at,created_at}` |
| `POST /api/v1/sponsorship/funds/{fund_id}/close` | Admin; `{ "disposition":"refund", "reason":"..." }` or `{ "disposition":"transfer", "target_fund_id":2, "reason":"..." }` | Updated fund/close result |
| `GET /api/v1/sponsorship/funds/{fund_id}/dashboard?from=YYYY-MM-DD&to=YYYY-MM-DD` | Admin | `{ "fund_id":1,"from":"YYYY-MM-DD","to":"YYYY-MM-DD","balance":"0.00","total_contributed":"0.00","total_spent":"0.00","students_covered":0,"average_spend_per_student_per_day":"0.00","spend_by_day":[{"date":"YYYY-MM-DD","amount":"0.00"}],"spend_by_meal_type":[{"meal_type":"lunch","amount":"0.00"}],"spend_by_class":[{"class_room":"P1","amount":"0.00"}],"projected_days_remaining":null}` |
| `GET /api/v1/sponsorship/funds/{fund_id}/report?from=YYYY-MM-DD&to=YYYY-MM-DD&hide_names=true&format=json` | Admin | `{ "fund":"Fund A","from":"YYYY-MM-DD","to":"YYYY-MM-DD","totals":{"meals":0,"amount":"0.00","students_covered":0},"students":[{"class_room":"P1","meals":0,"amount":"0.00","student":"S-0000001"}],"by_class":[{"class_room":"P1","meals":0,"amount":"0.00","students":0}]}`. `format=csv|pdf` returns a file; large/async CSV returns `{code:202,message,token}`. |
| `GET /api/v1/sponsorship/allocations` | Admin | Paginated Allocation objects |
| `POST /api/v1/sponsorship/allocations` | Admin; allocation body below | Allocation object |
| `POST /api/v1/sponsorship/allocations/bulk` | Admin; `{ "allocations":[AllocationInput,...] }` | Bulk result with created/failed rows |
| `POST /api/v1/sponsorship/allocations/{allocation_id}/deactivate` | Admin; optional `{ "reason":"..." }` | Updated allocation |

Allocation input:

```json
{
  "fund_id":1, "student_id":"uuid", "meal_types":["breakfast","lunch"],
  "daily_cap":"10000.00", "per_meal_cap":"5000.00",
  "valid_from":"2026-01-01", "valid_to":"2026-12-31",
  "priority":1, "is_active":true
}
```

Fund response fields: `id,name,sponsor_name,contact,description,status,start_date,
end_date,alert_threshold,balance,students_covered,created_at`.

## Users, schools, items, cards, and lists

Resource endpoints are mostly admin-only. Many historical write/list handlers
use POST even for lookup; the body fields below describe their filters or IDs.
The list endpoints under `/list/` are separate GET endpoints.

| Method and path | Request | Response |
| --- | --- | --- |
| `POST /api/v1/resources/users-list/` | `{ "search":"", "role":"student", "page":1 }` | Paginated user results |
| `POST /api/v1/resources/inactive-users-list/` | `{ "search":"", "role":"student", "page":1 }` | Paginated inactive user results |
| `POST /api/v1/resources/student-details` | `{ "student_id":"uuid" }` | `{id,first_name,middle_name,last_name,gender,class_room,school,school_id,profile_picture,transactions:[Transaction],rfid_card:Card|null,parents:[Parent],password_set,sponsorships:[{fund_name,meal_types,daily_cap,valid_to}],insufficient_meal_count,strike_limit}` |
| `POST /api/v1/resources/parent-details` | `{ "parent_id":"uuid" }` | `{id,first_name,username,middle_name,last_name,parent_type,email,mobile_number,gender,school,students:[Student],password_set}` |
| `POST /api/v1/resources/operator-details` | `{ "operator_id":"uuid" }` | `{id,first_name,middle_name,last_name,username,email,mobile_number,gender,school,sessions:[{id,status,type,start_at,end_at,updated_at}],school_id,password_set}` |
| `POST /api/v1/resources/admin-details` | `{ "admin_id":"uuid" }` | `{id,first_name,middle_name,last_name,username,email,mobile_number,gender,school,school_id,password_set}` |
| `POST /api/v1/resources/staff-details` | `{ "staff_id":"uuid" }` | `{id,first_name,middle_name,last_name,gender,email,username,mobile_number,school,school_id,profile_picture,rfid_card:Card|null,transactions:[Transaction],password_set}` |
| `POST /api/v1/resources/school-list/` | `{ "search":"", "page":1 }` | Paginated `[{id,name,location,number}]` |
| `POST /api/v1/resources/create-school` | `{ "name":"...", "location":"...", "number":"..." }` | School object |
| `POST /api/v1/resources/delete-school` | `{ "school_id":1 }` | Message result |
| `POST /api/v1/resources/create-item` | Admin + `MENU`; `{ "name":"Rice", "price":"2500.00", "is_active":true }` | CanteenItem `{id,name,price,is_active,created_at,updated_at}` |
| `POST /api/v1/resources/item-list/` | `{ "search":"", "page":1 }` | Paginated item objects |
| `POST /api/v1/resources/edit-item` | `{ "item_id":"uuid", ...partial CanteenItem fields... }` | `{ "message":"Item updated successfully", "item": CanteenItem }` |
| `POST /api/v1/resources/delete-item` | `{ "item_id":"uuid" }` | Message result; active preorder conflict returns 409 |
| `POST /api/v1/resources/create-card` | Admin; Card create body below | `{ "message":"Asha card created successfully", "rfidcard":Card }` |
| `POST /api/v1/resources/edit-card` | Admin; `{ "card_id":"uuid", ...partial card fields... }` | `{ "message":"User updated successfully", "user":Card }` |
| `POST /api/v1/resources/card-list/` | `{ "search":"", "page":1 }` | Paginated card objects |
| `POST /api/v1/resources/card-details` | `{ "card_number":"00012345" }` or `{ "card_id":"uuid" }` | Card and owner details |
| `POST /api/v1/resources/delete-card` | `{ "card_id":"uuid" }` | Message result |
| `POST /api/v1/resources/activate-deactivate-card` | `{ "card_id":"uuid", "action":"deactivate" }` (`activate|deactivate`) | `{ "message":"...", "card_id":"uuid", "is_active":false }` |
| `POST /api/v1/resources/reset-strikes` | `{ "card_id":"uuid", "reason":"..." }` | Updated strike count/result |
| `POST /api/v1/resources/replace-card` | Replace body below | New card and replacement result |
| `POST /api/v1/resources/notifications/` | `{}` | `[{"id":"uuid","message":"...","status":"pending","title":"...","type":"...","created_at":"...","recipient":"uuid"}]` |
| `POST /api/v1/resources/all-notifications/` | `{ "page":1 }` | Paginated notifications |
| `GET /api/v1/list/schools` | None | School array `[{"id":1,"name":"...","location":"...","number":"..."}]` |
| `GET /api/v1/list/parents` | None | Parent array |
| `GET /api/v1/list/students` | None | Student array |
| `GET /api/v1/list/staffs` | None | Staff array |
| `GET /api/v1/list/canteen-items` | None | Canteen item array |
| `GET /api/v1/list/cards` | None | Card array |

Card create body (omit `card_number` only when providing `card_uid`):

```json
{
  "student_or_staff":"user-uuid", "card_number":"00012345",
  "card_uid":"04A1B2C3D4E5F6", "balance":"0.00", "is_active":false,
  "issued_date":"2026-10-10"
}
```

At least one of `card_number` or `card_uid` is required. If only UID is sent,
the server generates a card number. UID is uppercase hex with separators
removed; physical card equivalence verification is documented in
[`card-identifiers.md`](card-identifiers.md). Never expose a full parent phone
number through deposit responses.

Create-card response is `{ "message":"Asha card created successfully", "rfidcard": Card }`.
Edit-card request requires `card_id`; response is `{ "message":"User updated successfully", "user": Card }`.
Card activation uses an `action`, not an `is_active` field. Reset-strikes body
is `{ "card_id":"uuid", "reason":"Verified by admin" }` and returns the Card.
Card details body is `{ "card_id":"uuid" }`.

Replace body:

```json
{"old_card_id":"uuid","new_card_number":"00012346","card_uid":"04A1B2C3D4E5F7","reason":"Damaged","carry_balance":true}
```

## Sessions, scans, and transactions

| Method and path | Access | Request | Response |
| --- | --- | --- | --- |
| `POST /api/v1/sessions/start-session` | Operator | `{ "type":"lunch" }` (`type` optional; default breakfast) | Session object |
| `POST /api/v1/sessions/end-session` | Operator | `{ "session_id":"uuid", "expected_cash":"5000.00", "reason":"..." }` | Exactly `{ "scanned_value":"...", "penalty_value":"...", "expected_cash":"...", "variance":"...", "status":"balanced|variance" }` |
| `GET /api/v1/sessions/active-session` | Authenticated operator | None | Session object; if none, HTTP 404 `{ "detail":"No active session found.", "code":"SESSION_NOT_ACTIVE" }` |
| `POST /api/v1/sessions/session-list` | Admin/operator | `{ "session_id":"uuid", "search":"" }` (accepted but currently ignored) | Array of at most 10 own sessions for operator or 20 sessions for admin |
| `POST /api/v1/sessions/scan-card` | Operator; throttled | Scan request below | ScannedData response below; HTTP 201 first scan, HTTP 200 idempotent replay |
| `POST /api/v1/sessions/scanned-data/` | Admin/operator | `{ "session_id":"uuid", "search":"" }` | Paginated scan records |
| `POST /api/v1/sessions/transaction-list/` | Admin/operator; parent gets own children only | `{ "search":"" }` | Paginated transaction objects |

Scan request (exactly one identifier):

```json
{
  "session_id":"session-uuid", "card_number":"00012345",
  "item_id":"item-uuid", "client_scan_id":"client-generated-uuid",
  "scan_source":"usb"
}
```

For NFC replace `card_number` with `card_uid` and set `scan_source` to `nfc`.
Valid source values are `usb|nfc|manual`. `client_scan_id` makes retries
idempotent. Scan response:

```json
{
  "id":"uuid", "session":"uuid", "student_name":"Asha Musa",
  "card_number":"00012345", "item_name":"Rice", "item_price":"2500.00",
  "scanned_at":"2026-10-10T12:00:00+03:00", "scan_source":"usb",
  "preorder_fulfilled":false,
  "payment_breakdown":[{"source":"wallet","amount":"2500.00"}],
  "status":"success", "insufficient_meal_count":0, "strike_limit":10
}
```

`payment_breakdown.source` can be `wallet`, `fund`, or `preorder`; sponsor
entries may include `fund_name` and a fund identifier. Common scan errors include
`CARD_IDENTIFIER_REQUIRED`, `CARD_NOT_FOUND`, `CARD_INACTIVE`,
`SESSION_NOT_ACTIVE`, `ITEM_INACTIVE`, `DUPLICATE_ITEM_IN_SESSION`,
`ITEM_BLOCKED`, `FEATURE_DISABLED`, `CLIENT_SCAN_ID_CONFLICT`, and
`OUT_OF_STOCK`.

## Wallet, deposits, statements, and reversals

Wallet deposit endpoints use `/api/v1/wallet/` and legacy `/wallet/` aliases.

| Method and path | Access | Request / query | Response |
| --- | --- | --- | --- |
| `POST /api/v1/wallet/deposit/create` | Parent or admin, scoped to parent child | `{ "card_number":"00012345", "amount":"10000.00", "payment_method":"cash", "provider":null, "reference":"bank slip or provider ref" }` | `{ "code":201,"message":"...","deposit":Deposit }` |
| `GET /api/v1/wallet/deposit/list?payment_method=cash&provider=&status=pending&from=YYYY-MM-DD&to=YYYY-MM-DD` | Parent sees own submissions; admin sees scoped deposits | Filters optional | Standard paginated Deposit objects |
| `POST /api/v1/wallet/deposit/process` | Admin | `{ "deposit_id":"uuid", "action":"process", "reason":"optional" }` | Process: `{ "code":200,"message":"...","deposit":Deposit,"ledger":... }`; fail: `{ "code":200,"message":"..." }` |
| `GET /api/v1/wallet/ledger/card?card_number=00012345&page=1&page_size=50` | Owner parent/admin/operator as permitted; `LEDGER_UI` | Card number required | Paginated `[{timestamp,event_type,event_type_display,amount,balance_before,balance_after,description}]` |
| `GET /api/v1/wallet/statement.pdf?child_id=uuid&from=YYYY-MM-DD&to=YYYY-MM-DD` | Parent's linked child or admin | Required child/date range; maximum 12 months | `application/pdf` attachment, not JSON |
| `POST /api/v1/wallet/transaction/reverse` | Admin/operator; `PAYMENTS` | `{ "transaction_id":"uuid", "reason":"...", "reversed_by_id":"uuid" }` (`reversed_by_id` optional) | Reversed transaction object; reversal is auditable and not a hard delete |

Deposit response fields:

```json
{
  "id":"uuid", "control_number":"12345678901", "card_number":"00012345",
  "student_name":"Asha", "amount":"10000.00", "status":"pending",
  "processed_at":null, "submitted_by":"uuid", "submitted_by_name":"...",
  "payment_method":"cash", "provider":null, "reference":"receipt-42",
  "phone_masked":"+255 7** *** 678", "created_at":"..."
}
```

`payment_method` is `cash|mobile_money`; cash requires `provider:null`, while
mobile money requires a provider. `phone_masked` is never the full number.

## Double-entry ledger

Ledger reads require the `LEDGER_UI` feature and admin access unless otherwise
specified. Date filters use `from` and `to`; pagination is 50/page where the
endpoint returns a list.

| Method and path | Query | Response |
| --- | --- | --- |
| `GET /api/v1/ledger/journal` | `from,to,event_type,page,page_size` | Paginated journal entries `{id,event_type,memo,created_at,ref_transaction,ref_deposit,lines:[...]}` |
| `GET /api/v1/ledger/journal/{entry_id}` | None | One journal entry |
| `GET /api/v1/ledger/cards/{card_id}/statement` | `from,to,page,page_size` | Paginated card journal lines `{id,entry_id,event_type,memo,account,direction,amount,balance_after,created_at}` |
| `GET /api/v1/ledger/funds/{fund_id}/statement` | `from,to,page,page_size` | Paginated fund journal lines |
| `GET /api/v1/ledger/accounts/{code}/statement` | `from,to,page,page_size` | Paginated account journal lines |
| `GET /api/v1/ledger/trial-balance?as_of=YYYY-MM-DD` | Optional as_of | `{ "as_of":"YYYY-MM-DD", "accounts":[{"account":"1000","name":"...","debit":"0.00","credit":"0.00","net":"0.00"}] }` |
| `GET /api/v1/ledger/integrity` | None | `{ "ok":true,"checked_cards":0,"mismatches":[] }` (integrity result) |

Journal line shape: `{ "id":"uuid", "account":"2000", "account_name":"Card wallets", "rfid_card":"uuid-or-null", "direction":"debit|credit", "amount":"0.00", "balance_after":"0.00" }`.

## Imports and exports

### Imports

| Method and path | Access | Request | Response |
| --- | --- | --- | --- |
| `GET /api/v1/imports/template` | Admin | Optional `format` query | CSV template download |
| `POST /api/v1/imports/upload` | Admin; multipart form | `file` (CSV/XLSX), `dry_run` (bool, default true), `mode` (`best_effort|all_or_nothing`) | `{ "dry_run":true,"mode":"best_effort","summary":{"total":1,"valid":1,"errors":0},"rows":[{"row_number":2,"first_name":"...","last_name":"...","card_number":"...","status":"valid","errors":[],"warnings":[]}] }` |
| `POST /api/v1/imports/commit` | Admin; multipart form | Same uploaded file field `file`; `mode` (`best_effort|all_or_nothing`). This endpoint re-parses/revalidates the supplied file; there is no upload_id. | `{ "message":"Import committed.","mode":"best_effort","all_or_nothing_aborted":false,"imported_count":1,"skipped_rows":[],"imported":[],"rows":[] }` |

### Exports

All export generation routes are POST and accept:

```json
{
  "export_format":"csv", "async_mode":false,
  "from_date":"2026-10-01", "to_date":"2026-10-10",
  "status":"", "search":"", "class_room":"", "active":null
}
```

`export_format` is `csv|xlsx`; other fields are optional filters. Routes are
`POST /api/v1/exports/transactions`, `/students`, `/deposits`,
`/analytics_sales`, `/analytics_wallet_health`, and `/analytics_operators`.
Inline exports return a downloadable file. Queued responses are
`{ "code":202,"message":"Export queued.","token":"short-lived-token" }`.
Poll/download with `GET /api/v1/exports/download/{token}`; while pending it
returns `{ "code":202,"message":"Export is still processing." }`, and once
ready it returns the file bytes with attachment headers.

## Audit log and SMS

| Method and path | Access | Request/query | Response |
| --- | --- | --- | --- |
| `GET /api/v1/audit/logs` (also `/logs/`) | Admin | `page` | Paginated audit records, including actor/action/object/time and sanitized before/after details |
| `POST /api/v1/sms/opt-out` (also slash alias) | Authenticated user | `{ "sms_opt_out":true }` | `{ "sms_opt_out":true }` |
| `GET /api/v1/sms/logs` (also slash alias) | Admin | `page` | Paginated SMS logs `{id,recipient,phone,body,provider,provider_sid,status,error,segments,cost_estimate,created_at,sent_at}`; sensitive values should be handled as private data |

## School-system integrations

Base path: `/integrations/v1/`. Sync requests authenticate with a provisioned
integration API key (send `Authorization: Bearer <api-key>`). Administrative
key/webhook endpoints require an authenticated admin. For parent/student rows,
accepted keys are `external_id` (required), `first_name` and `last_name`
(required), plus optional `middle_name,email,mobile_number,gender,class_room`.
Gender, when supplied, is `M|F`. Parent sync creates/updates role `parent`;
student sync creates/updates role `student`. Class rows require
`external_id` and `name`. `source_system` is required; maximum 500 rows per
request.

```json
{
  "source_system":"school-sis", "dry_run":false,
  "rows":[{"external_id":"S-1001","first_name":"Asha","last_name":"Musa"}]
}
```

Class example: `{ "source_system":"school-sis", "dry_run":true,
"rows":[{"external_id":"C-01","name":"Standard 1"}] }`.

| Method and path | Access | Response |
| --- | --- | --- |
| `POST /integrations/v1/students/sync` | Integration API key | `{ "created":1,"updated":0,"failed":0,"results":[{"index":0,"external_id":"S-1001","status":"created"}] }` |
| `POST /integrations/v1/parents/sync` | Integration API key | Same sync response |
| `POST /integrations/v1/classes/sync` | Integration API key | Same sync response |
| `GET /integrations/v1/admin/keys` | Admin | Array of key metadata; raw key is never shown again |
| `POST /integrations/v1/admin/keys` | Admin; `{ "name":"School SIS" }` | `{ "id":"...","name":"School SIS","prefix":"...","api_key":"one-time-secret","created_at":"..." }` |
| `POST /integrations/v1/admin/keys/{key_id}/revoke` | Admin | `{ "id":"...","revoked_at":"..." }` |
| `POST /integrations/v1/admin/keys/{key_id}/rotate` | Admin | New key response; secret shown once |
| `GET /integrations/v1/admin/webhooks` | Admin | Array of webhook endpoints |
| `POST /integrations/v1/admin/webhooks` | Admin; `{ "url":"https://example.test/hook","events":["meal.purchased","deposit.processed"] }` | `{ "id":"uuid","url":"https://...","events":[...],"is_active":true,"created_at":"...","secret":"one-time-signing-secret" }` |
| `PATCH /integrations/v1/admin/webhooks/{endpoint_id}` | Admin; any of `{ "url":"https://...", "events":[...], "is_active":false }` | Updated endpoint; secret is not returned |
| `GET /integrations/v1/admin/webhook-deliveries` | Admin | Array of up to 100 `{id,endpoint_id,event,status_code,attempts,delivered_at,last_error,created_at}` |
| `GET /integrations/v1/admin/sync-log` | Admin | Array of up to 100 `{id,endpoint,dry_run,created,updated,failed,results,created_at}` |

Allowed webhook events: `meal.purchased`, `deposit.processed`, `balance.low`,
`card.replaced`. Webhook URLs must use HTTPS. Treat API keys and webhook
secrets as passwords; they are returned once only.

## Operational and browser routes (not app JSON APIs)

| Method and path | Access | Response |
| --- | --- | --- |
| `GET /health` or `/health/` | Public | Liveness JSON; does not expose dependencies |
| `GET /status` or `/status/` | Restricted operational access | Dependency/status JSON; do not expose publicly |
| `/admin-auth/` | Django admin staff | HTML admin site |
| `/api-auth/` | DRF browsable API login/logout | HTML |

## Client implementation checklist

1. Use `/api/v1/` for new application clients, bearer authentication, and the
   endpoint-specific role listed above.
2. Preserve money as decimal strings/decimal arithmetic and timestamps as
   timezone-aware values.
3. Do not retry non-idempotent operations blindly. Use `client_scan_id` for
   scans and `idempotency_key` for preorders.
4. Do not expose a full phone number, invite URL, API key, webhook secret, or
   password in logs or analytics.
5. For parent screens, handle ownership-scoped 403/404 responses without
   leaking whether another family's record exists.
6. When changing API code, update this document, [`api-contract.md`](api-contract.md),
   and [`error-codes.md`](error-codes.md) as applicable; run the relevant
   backend tests and inspect the committed schema diff as a validation aid. The
   JSON contract is written here and is not delegated to generated docs.
