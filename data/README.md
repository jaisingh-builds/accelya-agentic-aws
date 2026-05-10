# Synthetic Data Pack

> **Synthetic data only. No real airline customer data, ever.**
> See `docs/data-safety.md`.

## What's here

| File | Purpose | First used |
|---|---|---|
| `synthetic_ticket_issues.json` | 500 ticket-issue events (494 valid + 6 deliberately malformed) | D2 Lab 2, D5 Lab 1 |
| `synthetic_settlements.csv` | 100 BSP settlement records, BSP-2026-W19 | D6 Lab 1, D6 Lab 2 |
| `synthetic_cancellations.json` | 50 cancellation events for streaming | D7 Lab 1, D8 Lab 1 |
| `generate_synthetic.py` | Regeneration script — produces all the above with fresh randomisation | Trainer-only |

## Schema (programme contract — locked from Day 4)

All synthetic records use lowercase snake_case:

```
pnr                — 6-char alphanumeric (e.g. "6X7Y8Z")
airline_code       — 2-char IATA (e.g. "AI", "BA", "EK")
fare_class         — 1-char (e.g. "Y", "J", "F")
od_pair            — "<3-char>-<3-char>" (e.g. "BOM-DEL")
settlement_date    — ISO 8601 date (e.g. "2026-05-09")
ticket_number      — "<3>-<10>" (e.g. "098-2400000001")
issue_date         — ISO 8601 date
fare_amount        — decimal number (e.g. 2845.0)
currency           — ISO 4217 (e.g. "INR", "USD")
agency_iata        — 8-char IATA agency code (e.g. "14300017")
source_system      — "BSP" / "ARC"
bsp_cycle          — "<YYYY>-W<NN>" (e.g. "2026-W19")
settlement_id      — "BSP-<YYYY>-W<NN>-<airline>-<seq>"
```

## Deliberately malformed records (for Lab quarantine demos)

`synthetic_ticket_issues.json` contains 6 records with intentional defects:

| Index | Defect | Should be caught by |
|---|---|---|
| 7 | Missing `fare_class` | Schema validator → `quarantine/schema_drift/` |
| 42 | `airline_code` = "XYZ" (invalid IATA) | Reference-data validator → `quarantine/reference_drift/` |
| 89 | `fare_amount` = "n/a" (string in numeric field) | Type validator → `quarantine/type_error/` |
| 156 | `pnr` = "" (empty required field) | Required-field validator → `quarantine/schema_drift/` |
| 233 | Duplicate of record 232 | Idempotency check → skip silently (`row#` PK) |
| 401 | Future-dated `settlement_date` (year 2099) | Business-rule validator → `quarantine/business_rule/` |

Lab 2 (D5) asks you to find these. Your validator should land 494 records in `validated/` and 6 in `quarantine/<reason>/`.

## Regenerating

```bash
python3 scripts/generate_synthetic.py
# Writes fresh:
#   data/synthetic_ticket_issues.json
#   data/synthetic_settlements.csv
#   data/synthetic_cancellations.json
```

Re-running produces NEW random PNRs / ticket numbers each time. The 6 malformed records are seeded with fixed indices so labs are reproducible.

---

*The synthetic pack is checked into Git for cohort access. Do NOT commit any locally edited or augmented copies that may have been mixed with real data.*
