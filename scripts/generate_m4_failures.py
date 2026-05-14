#!/usr/bin/env python3
"""
generate_m4_failures.py — regenerate the 5 synthetic broken files for Day 4 Lab 2.

Files generated under data/m4-failures/:
  01-schema-drift.json    — 100 rows; row 47 has wrong field; row 89 has string instead of number
  02-partial.json         — truncated mid-row 31 (intentionally invalid JSON)
  03-duplicate.json       — byte-identical copy of 01-schema-drift.json
  04-late-event.json      — 50 rows; issue_date is 95 days ago from script run time
  05-malformed.json       — 100 rows; row 14 unescaped quote; row 67 trailing comma

Usage:
  python3 scripts/generate_m4_failures.py

Idempotent for 01/02/03/05 (deterministic content). 04 shifts daily because
"95 days ago" depends on now() — that's intentional so the lab feels live.
"""
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "m4-failures"
OUT.mkdir(parents=True, exist_ok=True)


def write_schema_drift():
    """01 — 100 rows; row 47 has wrong field name; row 89 has string instead of number."""
    records = []
    for i in range(100):
        rec = {
            "settlement_id": f"BSP-2026-W19-AI234-{i:03d}",
            "bsp_cycle":     "2026-W19",
            "airline_code":  "AI",
            "pnr":           f"{chr(65+i%26)}{chr(66+i%26)}{i:04d}",
            "fare_class":    ["Y","J","F"][i%3],
            "od_pair":       "BOM-LHR",
            "ticket_number": f"098-{i+1000000:013d}",
            "issue_date":    "2026-05-08T11:42:00+05:30",
            "fare_amount":   2845.0 + i,
            "currency":      "INR",
            "agency_iata":   "14305820",
            "source_system": "BSP",
        }
        # Inject schema drift on row 47: wrong field name
        if i == 47:
            rec["fare_currency"] = rec.pop("currency")
        # Inject type mismatch on row 89: string instead of number
        if i == 89:
            rec["fare_amount"] = str(rec["fare_amount"])
        records.append(rec)
    path = OUT / "01-schema-drift.json"
    path.write_text(json.dumps(records, indent=2))
    print(f"  ✓ {path} — 100 rows, defects on rows 47 + 89")
    return path


def write_partial():
    """02 — truncated mid-row 31 (intentionally invalid JSON)."""
    records = [
        {
            "settlement_id": f"BSP-2026-W19-BA234-{i:03d}",
            "bsp_cycle":     "2026-W19",
            "airline_code":  "BA",
            "pnr":           f"{chr(65+i%26)}{chr(66+i%26)}{i:04d}",
            "fare_class":    "Y",
            "od_pair":       "LHR-JFK",
            "ticket_number": f"125-{i+2000000:013d}",
            "issue_date":    "2026-05-08T11:42:00+00:00",
            "fare_amount":   400.0 + i,
            "currency":      "GBP",
            "agency_iata":   "14305820",
            "source_system": "BSP",
        }
        for i in range(100)
    ]
    text = json.dumps(records, indent=2)
    # Find row-31 closing brace position; truncate inside it
    target = text.find('"settlement_id": "BSP-2026-W19-BA234-031"')
    mid = text.find("\n", target + 100)
    path = OUT / "02-partial.json"
    path.write_text(text[:mid])
    print(f"  ✓ {path} — truncated mid-row 31 (intentionally invalid JSON)")
    return path


def write_duplicate(source_path):
    """03 — byte-identical copy of 01."""
    path = OUT / "03-duplicate.json"
    shutil.copy(source_path, path)
    print(f"  ✓ {path} — byte-identical to 01-schema-drift.json")
    return path


def write_late_event():
    """04 — 50 rows; issue_date is 95 days ago from now."""
    late_date = (datetime.now(timezone.utc) - timedelta(days=95)).isoformat()
    records = [
        {
            "settlement_id": f"BSP-2026-W08-EK234-{i:03d}",
            "bsp_cycle":     "2026-W08",
            "airline_code":  "EK",
            "pnr":           f"{chr(65+i%26)}{chr(66+i%26)}{i:04d}",
            "fare_class":    "J",
            "od_pair":       "DXB-LHR",
            "ticket_number": f"176-{i+3000000:013d}",
            "issue_date":    late_date,
            "fare_amount":   1500.0 + i,
            "currency":      "AED",
            "agency_iata":   "14305820",
            "source_system": "BSP",
            "event_date":    late_date,
        }
        for i in range(50)
    ]
    path = OUT / "04-late-event.json"
    path.write_text(json.dumps(records, indent=2))
    print(f"  ✓ {path} — 50 rows, issue_date 95 days ago ({late_date[:10]})")
    return path


def write_malformed():
    """05 — 100 rows; row 14 unescaped quote; row 67 trailing comma."""
    records = [
        {
            "settlement_id": f"BSP-2026-W19-QF234-{i:03d}",
            "bsp_cycle":     "2026-W19",
            "airline_code":  "QF",
            "pnr":           f"{chr(65+i%26)}{chr(66+i%26)}{i:04d}",
            "fare_class":    "Y",
            "od_pair":       "SYD-LAX",
            "ticket_number": f"081-{i+4000000:013d}",
            "issue_date":    "2026-05-08T11:42:00+10:00",
            "fare_amount":   2200.0 + i,
            "currency":      "AUD",
            "agency_iata":   "14305820",
            "source_system": "BSP",
        }
        for i in range(100)
    ]
    text = json.dumps(records, indent=2)
    # Inject malformations
    text = text.replace('"pnr": "ABCD0014"', '"pnr": "ABCD"0014"', 1)   # unescaped quote
    text = text.replace('"fare_amount": 2267.0,', '"fare_amount": 2267.0,,', 1)   # trailing comma
    path = OUT / "05-malformed.json"
    path.write_text(text)
    print(f"  ✓ {path} — 100 rows, parse errors on rows 14 + 67")
    return path


def main():
    print(f"Regenerating M4 broken files into {OUT}/")
    print()
    p01 = write_schema_drift()
    write_partial()
    write_duplicate(p01)
    write_late_event()
    write_malformed()
    print()
    print("All 5 files written. Day 4 Lab 2 reads from data/m4-failures/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
