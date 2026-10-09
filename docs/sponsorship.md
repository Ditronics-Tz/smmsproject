# Sponsorship and bursary funds

Sponsorship is managed by school administrators only. Parents do not get fund,
sponsor, contribution, or allocation endpoints. A parent may see a fund's name
and meal payment amounts only on transactions belonging to their linked child.
Names are hidden by default in sponsor reports; the current API does not grant
sponsors login access. Any sponsor portal requires a separate authorization,
fund-scope, and privacy review.

## Posting flows

| Event | Debit | Credit | Idempotency |
| --- | --- | --- | --- |
| Contribution | 1000 bank/cash (1100 for mobile money) | 2200 sponsor fund liability (fund dimension) | `fund-contrib:<contribution-id>` |
| Sponsored meal | 2200 sponsor fund liability (fund dimension) | 4000 meal revenue | `fund-spend:<transaction-id>:<fund-id>` |
| Refund on close | 2200 sponsor fund liability (fund dimension) | 1000 bank/cash | `fund-refund:<close-id>` |
| Transfer on close | 2200 source fund | 2200 target fund | `fund-transfer:<close-id>` |
| Reversal | Exact mirror of each source journal entry, including fund dimension | Exact mirror | `reversal:<transaction-id>:<journal-id>` |

Funds cannot be spent below zero. At scan time, eligible active allocations are
applied by priority after a matching pre-order and before the student's wallet.
Per-meal and daily caps are measured from non-voided fund payment parts. The
wallet pays the remainder; a normal insufficient-balance penalty applies only
to that remainder. `SPONSOR_FALLBACK_TO_WALLET` defaults to `True`; when false,
a partially covered meal is rejected rather than charging the wallet.

## Endpoint permissions

| Endpoint | Permission | Feature |
| --- | --- | --- |
| `GET/POST /sponsorship/funds` | Admin | `SPONSORSHIP` |
| `GET/PUT /sponsorship/funds/{id}` | Admin | `SPONSORSHIP` |
| `POST /sponsorship/funds/{id}/contribute` | Admin | `SPONSORSHIP` |
| `POST /sponsorship/funds/{id}/close` | Admin | `SPONSORSHIP` |
| `GET/POST /sponsorship/allocations`, `/bulk`, `/{id}/deactivate` | Admin | `SPONSORSHIP` |
| `GET /ledger/funds/{id}/statement` | Admin | `LEDGER_UI` |
| Fund dashboard and report | Admin | `SPONSORSHIP` |

Every mutation writes an AuditLog entry. Contributions require a reference or
reason; fund closure requires a reason and an explicit refund/transfer choice.
Fund reports default to stable anonymous student codes (`S-xxxxxxx`); names
are included only when an administrator explicitly requests `hide_names=false`.
