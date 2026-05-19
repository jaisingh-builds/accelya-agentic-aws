#!/usr/bin/env python3
"""
generate_m6_settlements.py — produce ~50K synthetic settlement rows for Day 6.

Output layout (one NDJSON file per Hive partition):
    data/m6-settlements/
      source_system=BSP/ingest_date=2026-05-09/part-00000.jsonl   (~3,000 rows)
      source_system=BSP/ingest_date=2026-05-10/part-00000.jsonl
      ...
      source_system=ATPCO/ingest_date=2026-05-12/part-00000.jsonl

Schema matches Day 6 v3 catalog (13 columns):
    settlement_id   STRING
    airline_code    STRING
    pnr             STRING
    fare_class      STRING
    od_pair         STRING
    ticket_number   STRING
    bsp_cycle       STRING
    issue_date      TIMESTAMP_MILLIS (ISO-8601 with offset; ETL normalises to UTC)
    fare_amount     DECIMAL(12,2)
    currency        STRING
    commission_pct  DECIMAL(5,4)
    refund_status   STRING | null
    agency_iata     STRING

The file is REPRODUCIBLE — fixed seed; running twice produces identical bytes.

Usage:
    python3 scripts/generate_m6_settlements.py
        # writes ~16 files under data/m6-settlements/
        # ~50K rows total, ~12 MB on disk

Day 6 Lab 1 step 3 (re-staging) pulls from this directory directly:
    bash scripts/upload_m6_settlements.sh <learner>
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "m6-settlements"

# Deterministic
random.seed(20260518)

# ── Configuration ─────────────────────────────────────────────────────────
SOURCE_SYSTEMS = ["BSP", "ARC", "ATPCO", "GDS"]
INGEST_DATES = [
    "2026-05-09",  # primary lab date
    "2026-05-10",  # additive partition for Lab 1 step 5
    "2026-05-11",  # Lab 3 additive-column file slots in here
    "2026-05-12",  # extra
]
ROWS_PER_PARTITION = 3000

# Realistic airline distribution: weighted by ~real BSP volume share
AIRLINES = [
    ("AI",   "BOM-LHR", "INR", 0.07),    # Air India
    ("BA",   "LHR-JFK", "GBP", 0.07),    # British Airways
    ("EK",   "DXB-LHR", "AED", 0.06),    # Emirates
    ("QF",   "SYD-LAX", "AUD", 0.07),    # Qantas
    ("LH",   "FRA-JFK", "EUR", 0.07),    # Lufthansa
    ("SQ",   "SIN-LHR", "SGD", 0.07),    # Singapore
    ("CX",   "HKG-LAX", "HKD", 0.07),    # Cathay
    ("UA",   "ORD-FRA", "USD", 0.06),    # United
    ("AF",   "CDG-JFK", "EUR", 0.07),    # Air France
    ("DL",   "ATL-LHR", "USD", 0.07),    # Delta
    ("KL",   "AMS-JFK", "EUR", 0.07),    # KLM
    ("TK",   "IST-JFK", "TRY", 0.07),    # Turkish
    ("EY",   "AUH-LHR", "AED", 0.06),    # Etihad
    ("QR",   "DOH-LHR", "QAR", 0.07),    # Qatar
]
AIRLINE_WEIGHTS = [3, 4, 5, 2, 4, 3, 2, 4, 3, 4, 2, 2, 2, 3]

FARE_CLASSES = [("Y", 0.55), ("M", 0.20), ("J", 0.20), ("F", 0.05)]
SOURCE_PREFIX = {"BSP": "098", "ARC": "104", "ATPCO": "081", "GDS": "176"}
REFUND_STATUS_POOL = [None, None, None, None, None, None, None,
                      "REQUESTED", "PROCESSED", "REJECTED"]


def _pnr(rng: random.Random) -> str:
    """6-char alphanumeric PNR."""
    return "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ2345678") for _ in range(6))


def _ticket_number(prefix: str, idx: int) -> str:
    return f"{prefix}-{idx:013d}"


def _fare_class(rng: random.Random) -> str:
    r = rng.random()
    cum = 0.0
    for cls, w in FARE_CLASSES:
        cum += w
        if r < cum:
            return cls
    return "Y"


def _fare_amount(rng: random.Random, fare_class: str) -> float:
    base = {"Y": 850.0, "M": 1200.0, "J": 4800.0, "F": 9500.0}[fare_class]
    # Realistic spread; never below 100
    val = base * rng.uniform(0.6, 1.8)
    return round(max(val, 100.0), 2)


def _bsp_cycle(ingest_date: str) -> str:
    # ISO week number; for our dates this maps cleanly:
    # 2026-05-09 + 2026-05-10 = W19; 2026-05-11 + 2026-05-12 = W20
    from datetime import date
    y, m, d = ingest_date.split("-")
    wk = date(int(y), int(m), int(d)).isocalendar()[1]
    return f"{y}-W{wk:02d}"


def _commission_pct(rng: random.Random, source: str) -> float:
    # ARC commissions tend higher; BSP standard 7%
    base = {"BSP": 0.0700, "ARC": 0.0900, "ATPCO": 0.0500, "GDS": 0.0650}[source]
    return round(base + rng.uniform(-0.0100, 0.0100), 4)


def generate_row(idx: int, source: str, ingest_date: str, rng: random.Random) -> dict:
    airline, od, currency, _ = rng.choices(AIRLINES, weights=AIRLINE_WEIGHTS, k=1)[0]
    fare_class = _fare_class(rng)
    fare_amount = _fare_amount(rng, fare_class)
    ticket_prefix = SOURCE_PREFIX[source]
    bsp_cycle = _bsp_cycle(ingest_date)

    return {
        "settlement_id": f"{source}-{bsp_cycle}-{airline}-{idx:06d}",
        "airline_code":  airline,
        "pnr":           _pnr(rng),
        "fare_class":    fare_class,
        "od_pair":       od,
        "ticket_number": _ticket_number(ticket_prefix, idx),
        "bsp_cycle":     bsp_cycle,
        "issue_date":    f"{ingest_date}T11:42:00+05:30",
        "fare_amount":   fare_amount,
        "currency":      currency,
        "commission_pct": _commission_pct(rng, source),
        "refund_status": rng.choice(REFUND_STATUS_POOL),
        "agency_iata":   f"143{rng.randint(0, 99999):05d}",
    }


def write_partition(source: str, ingest_date: str, n_rows: int,
                    start_idx: int, rng: random.Random) -> Path:
    partition_dir = OUT_DIR / f"source_system={source}" / f"ingest_date={ingest_date}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    out_path = partition_dir / "part-00000.jsonl"
    with out_path.open("w") as f:
        for i in range(n_rows):
            row = generate_row(start_idx + i, source, ingest_date, rng)
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return out_path


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating Day 6 synthetic settlements into {OUT_DIR}/")
    print()
    rng = random.Random(20260518)
    total_rows = 0
    total_files = 0
    start_idx = 100000  # avoid collision with Day-5 row indices

    for source in SOURCE_SYSTEMS:
        for ingest_date in INGEST_DATES:
            path = write_partition(source, ingest_date, ROWS_PER_PARTITION,
                                   start_idx, rng)
            size_kb = path.stat().st_size / 1024
            print(f"  ✓ {path.relative_to(ROOT)}  ({ROWS_PER_PARTITION} rows, {size_kb:.1f} KB)")
            start_idx += ROWS_PER_PARTITION
            total_rows += ROWS_PER_PARTITION
            total_files += 1

    print()
    print(f"Done. {total_files} files, {total_rows:,} rows total.")
    print(f"On-disk size: {sum(p.stat().st_size for p in OUT_DIR.rglob('*.jsonl')) / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
