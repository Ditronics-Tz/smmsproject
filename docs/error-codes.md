# API error codes

Error responses use a numeric `code` and a human-readable `message`.

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
| 429 | The request was throttled. Retry after the indicated interval. | 429 |
