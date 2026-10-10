# SMMS API developer handoff

Use the [complete API reference](API_COMPLETE_REFERENCE.md) as the self-contained
client contract. It lists the registered endpoint paths, methods, permissions,
request/query fields, response JSON structures, file responses, and common
errors. No generated-schema lookup is required to implement a client.

Supporting policy documents:

- [Frontend-facing API contract](api-contract.md)
- [Error codes](error-codes.md)
- [Permission matrix](permission-matrix.md)
- [Card identifier and NFC notes](card-identifiers.md)

For authenticated requests, use `Authorization: Bearer <token>`. Login is
`POST /api/v1/auth/login`; it returns the access token as `token` and refresh
token as `refresh`. New clients should use `/api/v1/`; legacy unversioned routes
exist for compatibility. Integration clients use `/integrations/v1/` and an
integration API key.

When changing API behavior, update `API_COMPLETE_REFERENCE.md`, the applicable
contract/error documentation, and tests in the same change. Never log secrets,
invite links, or full parent phone numbers.
