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
| 429 | The request was throttled. Retry after the indicated interval. | 429 |
