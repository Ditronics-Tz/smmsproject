# API error codes

Error responses use a `code` (numeric for legacy codes, string for named contract errors) and a human-readable `message`.

| Code | Meaning | HTTP status |
| --- | --- | --- |
| 400 | Request validation failed or required input is missing. | 400 |
| 403 | The authenticated user is not allowed to perform this action. | 403 |
| 404 | The requested resource does not exist. | 404 |
| 104 | The requested user ID is required. | 400 |
| 106 | A user ID is required. | 400 |
| 107 | The requested user or linked user does not exist. | 404 |
| 108 | The username is already in use. | 400 |
| 122 | The mobile number is already in use. | 400 |
| 123 | The email address is already in use. | 400 |
| 124 | The password reset or invite token is invalid, expired, or already used. | 400 |
| `FEATURE_DISABLED` | The requested optional feature is disabled for this deployment. | 403 |
| `CARD_IDENTIFIER_REQUIRED` | Supply exactly one of `card_number` or `card_uid`. | 400 |
| `INVALID_CARD_UID` | The UID is not 4, 7, or 10 bytes of hexadecimal after separator removal. | 400 |
| `CARD_UID_CONFLICT` | The UID conflicts with a registered UID or another card number. | 409 |
| `INVALID_SCAN_SOURCE` | The scan source is invalid for the supplied identifier. | 400 |
| `CLIENT_SCAN_ID_CONFLICT` | The idempotency key is already associated with another operator. | 409 |
| `DAILY_MENU_EXISTS` | A menu already exists for the requested date and meal type. | 409 |
| `DAILY_MENU_NOT_FOUND` | No menu exists for the requested date and meal type. | 404 |
| `ITEM_NOT_ON_MENU` | The scanned item is not on today's menu for this meal. | 403 |
| `ITEM_BLOCKED` | The student's parent has blocked the scanned canteen item. | 403 |
| `DAILY_LIMIT` | The purchase would exceed the student's configured daily spending limit. | 403 |
| `CHILD_NOT_LINKED` | The requested child is not linked to the authenticated parent. | 403 |
| `PARENT_REQUIRED` | Only a parent can manage child spending controls. | 403 |
| `OUT_OF_STOCK` | The item has no remaining inventory while stock enforcement is enabled. | 409 |
| `SPONSOR_FUNDS_EXHAUSTED` | Eligible sponsor allocations cannot cover the meal and wallet fallback is disabled. | 409 |
| `FUND_CLOSED` | A closed sponsor fund cannot be changed or closed again. | 409 |
| `FUND_NOT_ACTIVE` | The fund must be active for contributions, allocations, or a transfer target. | 409 |
| `ALLOCATION_OVERLAP` | This student already has an active allocation from the same fund. | 409 |
| `ALLOCATION_INACTIVE` | The allocation was already deactivated. | 409 |
| `PDF_EXPORT_UNAVAILABLE` | PDF rendering is unavailable on this server. | 501 |
| `STOCK_ADJUSTMENT_NEGATIVE` | The adjustment would make an inventory quantity negative. | 400 |
| `INVALID_DATE_RANGE` | Analytics `from`/`to` dates are malformed, reversed, or span too many days. | 400 |
| `INSIGHT_ALREADY_RESOLVED` | The anomaly has already been resolved. | 409 |
| `MENU_ITEM_HAS_PREORDERS` | A menu item cannot be removed while active pre-orders reference that menu. | 409 |
| `PREORDER_CUTOFF_PASSED` | The Tanzania-local ordering cutoff has passed. | 400 |
| `PREORDER_NO_MENU` | No menu exists for the requested date and meal. | 400 |
| `PREORDER_INSUFFICIENT_BALANCE` | The child has a negative balance or cannot cover the hold. | 400 |
| `PREORDER_NOT_CANCELLABLE` | The order is no longer placed or the cutoff has passed. | 400 |
| `PREORDER_QUANTITY_LIMIT` | The item quantity exceeds the configured maximum. | 400 |
| `PREORDER_DATE_OUT_OF_RANGE` | The requested date is outside the configured preorder window. | 400 |
| `PREORDER_ITEM_NOT_ON_MENU` | A requested item is not on the selected menu. | 400 |
| `PREORDER_CARD_INVALID` | The child does not have an active card eligible for this order. | 400 |
| `INVALID_PREORDER_REQUEST` | Required preorder fields are missing or malformed. | 400 |
| `PREORDER_CONFLICT` | An active order already exists for this child, date, and meal. | 409 |
| `IDEMPOTENCY_KEY_CONFLICT` | The idempotency key is associated with another child/order. | 409 |
| `INVALID_PAGINATION` | Page and page_size must be positive integers. | 400 |
| `INVALID_MENU_ITEMS` | Menu items must be unique active canteen items. | 400 |
| 429 | The request was throttled. Retry after the indicated interval. | 429 |
