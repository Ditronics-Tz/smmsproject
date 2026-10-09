# School-system integrations

Integration sync uses `/integrations/v1/{students,parents,classes}/sync`. Send
the one-time-issued key as `X-API-Key: <key>` (or `Authorization: Api-Key
<key>`). Keys are stored only as SHA-256 hashes, are scoped to the school of
their creating admin, throttled per key, and can be revoked or rotated. The
plaintext key is returned once at creation or rotation; keep it in the external
system's secret store.

Each sync request is JSON with `source_system`, `rows` (at most 500), and an
optional boolean `dry_run`. User rows require `external_id`, `first_name`, and
`last_name`; supported optional fields are `middle_name`, `email`,
`mobile_number`, `gender`, and `class_room`. Class rows require `external_id`
and `name`. Responses include created/updated/failed counts and a per-row
result. Repeating a source/external ID updates the same record. Integration
users start with unusable passwords; sync never changes passwords or account
roles. Admins can inspect recent sync logs.

Webhook endpoints accept only HTTPS URLs and the events `meal.purchased`,
`deposit.processed`, `balance.low`, and `card.replaced`. Delivery requests carry
`X-SMMS-Event` and `X-SMMS-Signature: sha256=<hex HMAC-SHA256>` over the exact
request body. The generated webhook secret is shown once. Celery retries
failures up to five attempts; status is visible in the delivery log. Targets
must resolve to public IP addresses to reduce SSRF risk.

## Scheduled adapter import

`SCHOOL_SYSTEM_ADAPTER` defaults to `csv`; custom adapters are selected using
`python.module.ClassName` and implement `BaseSchoolAdapter`. The CSV adapter
reads UTF-8 CSV files with headers configured in `SCHOOL_SYSTEM_STUDENTS_CSV`,
`SCHOOL_SYSTEM_PARENTS_CSV`, and `SCHOOL_SYSTEM_CLASSES_CSV`. Create an
integration key first and set its ID in `SCHOOL_SYSTEM_INTEGRATION_KEY_ID`.
Celery Beat runs daily at `SCHOOL_SYSTEM_SYNC_HOUR` and
`SCHOOL_SYSTEM_SYNC_MINUTE` (Celery timezone, default `Africa/Dar_es_Salaam`; defaults to 03:00). Set
`SCHOOL_SYSTEM_SYNC_DRY_RUN=true` to report rows without applying upserts.
