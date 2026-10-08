# Card identifiers and NFC UID mapping

## Investigation status

The required physical-card comparison has not yet been supplied. Faraja’s FE-51 phone-read results and five matching USB-reader/database records are needed before the byte-order or reader-format mapping can be called verified. No sample values are presented as real card evidence here.

Record exactly five cards in this table once the readings are collected:

| Physical card (label) | `card_number` in SMMS | USB reader output (verbatim) | Phone UID (verbatim) | Normalized UID hex | Same-card resolution verified? |
| --- | --- | --- | --- | --- | --- |
| 1 | Pending | Pending | Pending (Faraja FE-51) | Pending | No |
| 2 | Pending | Pending | Pending (Faraja FE-51) | Pending | No |
| 3 | Pending | Pending | Pending (Faraja FE-51) | Pending | No |
| 4 | Pending | Pending | Pending (Faraja FE-51) | Pending | No |
| 5 | Pending | Pending | Pending (Faraja FE-51) | Pending | No |

## Current normalization rule

`normalize_uid(value)` removes colons, hyphens, and whitespace, then uppercases the remaining characters. It accepts exactly 4-, 7-, or 10-byte UIDs represented as 8, 14, or 20 hexadecimal characters. It does not reverse byte order: the investigation has not established that reversal is needed. This is a syntax normalization only, not yet the verified USB-to-phone mapping rule.

Import verified associations with:

```powershell
python manage.py import_card_uids card-uids.csv --dry-run
python manage.py import_card_uids card-uids.csv
```

CSV headers are `card_number,uid_hex`. The import reports unknown cards, malformed UIDs, existing mappings, duplicate UIDs, and cross-identifier collisions; it applies no rows if conflicts are present. The acceptance criterion that a physical card resolves identically via USB and phone remains pending until the five real readings have been recorded and tested.
