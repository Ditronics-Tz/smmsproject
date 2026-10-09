# Wallet and strike-counter rules

The strike counter is `RFIDCard.insufficient_meal_count`. A penalty scan adds
one strike, up to the configured penalty/balance-floor behavior; a card at
`STRIKE_LIMIT` cannot be used for another meal until its count is lowered.

- Defaults: `STRIKE_LIMIT=10`, `PENALTY_FEE=500.00`, and
  `RFID_BALANCE_FLOOR=-500.00`; all are environment-overridable.
- Reversing a penalty transaction subtracts one strike, never below zero.
  Reversing a non-penalty transaction does not change strikes.
- Deposits do not reset strikes by default. Set
  `STRIKE_RESET_ON_DEPOSIT=True` to reset them when a deposit is processed.
- An administrator may reset one card via `POST /api/v1/resources/reset-strikes`
  with `{ "card_id": "<UUID>", "reason": "..." }`. The operation is row-locked
  and records before/after state and the reason in AuditLog.
- Scan responses, card details, and student details expose
  `insufficient_meal_count` and the configured `strike_limit`.

Reset is an explicit audited action; a normal deposit never resets the count
unless the environment setting is intentionally enabled.
