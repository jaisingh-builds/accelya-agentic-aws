#!/usr/bin/env python3
"""
generate_synthetic.py — produce the synthetic data pack.

Outputs (under data/):
  - synthetic_ticket_issues.json  (500 records: 494 valid + 6 deliberately malformed)
  - synthetic_settlements.csv     (100 settlement records, BSP-2026-W19)
  - synthetic_cancellations.json  (50 cancellation events for streaming labs)

Defect indices for synthetic_ticket_issues.json are fixed at:
  7, 42, 89, 156, 233, 401
(See data/README.md for what each defect looks like.)

Usage:
  python3 scripts/generate_synthetic.py
"""
import csv
import json
import random
import string
from datetime import date, datetime, timedelta
from pathlib import Path

# Reproducible for test_pack_v1, change to None for fully random each run
random.seed(42)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── reference data ────────────────────────────────────────────────────────
AIRLINES = ["AI", "BA", "EK", "QR", "SQ", "TG", "MH", "EY", "GF", "WY"]
FARE_CLASSES = ["Y", "B", "M", "K", "H", "J", "C", "D", "F", "A"]
ROUTES = [
    "BOM-DEL", "DEL-BOM", "BOM-LHR", "LHR-BOM", "DEL-DXB", "DXB-DEL",
    "BOM-SIN", "SIN-BOM", "DEL-JFK", "JFK-DEL", "BOM-FRA", "FRA-BOM",
]
CURRENCIES = ["INR", "USD", "GBP", "EUR", "AED", "SGD"]
CANCEL_REASONS = ["WX", "OP", "PAX", "TKT", "SCH"]


def random_pnr():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def random_ticket(airline_idx=98):
    return f"{airline_idx:03d}-{random.randint(1000000000, 9999999999)}"


def random_agency():
    return f"{random.randint(10000000, 99999999)}"


def random_amount(low=500.0, high=5000.0):
    return round(random.uniform(low, high), 2)


def random_date(start_offset=-30, end_offset=0):
    return (date.today() + timedelta(days=random.randint(start_offset, end_offset))).isoformat()


def make_valid_ticket_issue(seq):
    return {
        "pnr": random_pnr(),
        "airline_code": random.choice(AIRLINES),
        "fare_class": random.choice(FARE_CLASSES),
        "od_pair": random.choice(ROUTES),
        "settlement_date": random_date(-7, 7),
        "ticket_number": random_ticket(),
        "issue_date": random_date(-30, -1),
        "fare_amount": random_amount(),
        "currency": random.choice(CURRENCIES),
        "agency_iata": random_agency(),
        "source_system": "BSP",
        "seq": seq,
    }


# ── 1. Ticket issues with 6 deliberate defects ────────────────────────────
def make_ticket_issues():
    records = [make_valid_ticket_issue(i) for i in range(500)]

    # Defect 1: index 7 — missing fare_class
    del records[7]["fare_class"]

    # Defect 2: index 42 — invalid airline_code
    records[42]["airline_code"] = "XYZ"

    # Defect 3: index 89 — fare_amount as string
    records[89]["fare_amount"] = "n/a"

    # Defect 4: index 156 — empty pnr
    records[156]["pnr"] = ""

    # Defect 5: index 233 — exact duplicate of 232 (test idempotency)
    records[233] = dict(records[232])
    records[233]["seq"] = 233   # only seq differs

    # Defect 6: index 401 — future-dated settlement_date
    records[401]["settlement_date"] = "2099-12-31"

    return records


# ── 2. Settlement records ─────────────────────────────────────────────────
def make_settlements():
    rows = []
    for seq in range(100):
        airline = random.choice(AIRLINES)
        rows.append({
            "settlement_id": f"BSP-2026-W19-{airline}{random.randint(100,999)}-{seq+1:03d}",
            "bsp_cycle": "2026-W19",
            "airline_code": airline,
            "amount_local": random_amount(1000.0, 100000.0),
            "currency": random.choice(CURRENCIES),
            "pnr": random_pnr(),
            "issue_date": random_date(-14, -7),
            "ticket_number": random_ticket(),
            "agency_iata": random_agency(),
            "source_system": "BSP",
        })
    return rows


# ── 3. Cancellations (for streaming labs) ─────────────────────────────────
def make_cancellations():
    events = []
    base_time = datetime.utcnow() - timedelta(hours=2)
    for seq in range(50):
        event_time = base_time + timedelta(minutes=random.randint(0, 120))
        events.append({
            "event_id": f"evt-{seq+1:05d}",
            "event_type": "cancellation",
            "event_timestamp": event_time.isoformat() + "Z",
            "airline_code": random.choice(AIRLINES),
            "pnr": random_pnr(),
            "booking_date": random_date(-60, -1),
            "cancel_reason_code": random.choice(CANCEL_REASONS),
            "fare_amount": random_amount(),
            "currency": random.choice(CURRENCIES),
            "od_pair": random.choice(ROUTES),
        })
    return events


# ── write files ───────────────────────────────────────────────────────────
def main():
    ticket_issues = make_ticket_issues()
    settlements = make_settlements()
    cancellations = make_cancellations()

    # JSON: ticket issues
    p1 = DATA_DIR / "synthetic_ticket_issues.json"
    with p1.open("w") as f:
        json.dump(ticket_issues, f, indent=2)
    print(f"✓ {p1} ({len(ticket_issues)} records, 6 deliberate defects)")

    # CSV: settlements
    p2 = DATA_DIR / "synthetic_settlements.csv"
    with p2.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(settlements[0].keys()))
        writer.writeheader()
        writer.writerows(settlements)
    print(f"✓ {p2} ({len(settlements)} records)")

    # JSON: cancellations
    p3 = DATA_DIR / "synthetic_cancellations.json"
    with p3.open("w") as f:
        json.dump(cancellations, f, indent=2)
    print(f"✓ {p3} ({len(cancellations)} events)")

    print("\nDone. See data/README.md for schema + defect indices.")


if __name__ == "__main__":
    main()
