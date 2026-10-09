# Permission matrix

Admin-only endpoints use the application account role (`role == "admin"`),
not Django's `is_staff` flag. `is_superuser` is reserved for platform-owner
operations such as managing schools and administrator accounts; it is not a
general substitute for the admin role.

| Endpoint group | Admin | Operator | Parent | Staff | Student | Anonymous |
| --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/list/*` | Allow* | Deny | Deny | Deny | Deny | Deny |
| CreateSchool, CreateItem | Allow* | Deny | Deny | Deny | Deny | Deny |
| CardList, DeleteSchool, all-notifications | Allow | Deny | Deny | Deny | Deny | Deny |
| Audit logs, SMS logs, dependency status | Allow | Deny | Deny | Deny | Deny | Deny |
| `/integrations/v1/admin/*` key/webhook/sync-log management | Allow | Deny | Deny | Deny | Deny | Deny |
| `/integrations/v1/{students,parents,classes}/sync` | Integration key only | Deny | Deny | Deny | Deny | Deny |
| `/api/v1/wallet/statement.pdf` | Allow within admin scope | Deny | Own linked children only | Deny | Deny | Deny |
| `/api/v1/resources/reset-strikes` | Allow | Deny | Deny | Deny | Deny | Deny |

Integration routes also require the `INTEGRATIONS` feature; sync routes additionally
require a valid, active API key issued to an administrator in that school.
`*` Canteen-item operations also require the `MENU` feature to be enabled.
Automated role-matrix regression coverage is in
`smmsapp/tests/test_be03_permissions.py`.
