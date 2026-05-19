#!/usr/bin/env python3
"""
gen_m7_events.py — generate synthetic booking events for Day 7 Lab 3.

Produces NDJSON events matching the Day 7 envelope schema (5 event types).

Usage:
    python3 -m scripts.gen_m7_events \\
        --count 10000 \\
        --airlines AI,EK,LH,SQ \\
        --date-range 2026-05-01..2026-05-10 \\
        --out /tmp/m7-events-10k.jsonl

Lab 3 then pushes these events to Kinesis with three different PK strategies:
    Strategy A — pk = booking_id (random UUID; baseline distribution loses ordering)
    Strategy B — pk = airline_code:booking_date (deterministic + preserves order)

Hot-shard math is observable via CloudWatch `IncomingBytes` per shard.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

random.seed(20260719)


def _pnr(rng: random.Random) -> str:
    return "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ2345678") for _ in range(6))


def _ts(d: date, rng: random.Random) -> str:
    """ISO-8601 UTC timestamp within the booking_date."""
    secs = rng.randint(0, 86399)
    dt = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) + timedelta(seconds=secs)
    return dt.isoformat()


def make_event(rng: random.Random, airlines: list[str], dates: list[date],
               event_types: list[str]) -> dict:
    et = rng.choice(event_types)
    airline = rng.choice(airlines)
    booking_date = rng.choice(dates)
    pnr = _pnr(rng)
    event_time = _ts(booking_date, rng)
    ingest_time = datetime.now(timezone.utc).isoformat()

    base = {
        "event_id":      str(uuid.uuid4()),
        "event_type":    et,
        "event_time":    event_time,
        "ingest_time":   ingest_time,
        "airline_code":  airline,
        "booking_date":  booking_date.isoformat(),
        "pnr":           pnr,
        "source_system": rng.choice(["GDS", "DCS", "INVENTORY"]),
    }

    if et == "cancellation":
        base["payload"] = {
            "pnr": pnr,
            "cancel_reason_code": rng.choice(["WX", "OPS", "PAX", "MED"]),
            "cancellation_event_id": f"CXL-{uuid.uuid4().hex[:8]}",
        }
    elif et == "refund":
        base["payload"] = {
            "pnr": pnr,
            "original_cancel_event_id": f"CXL-{uuid.uuid4().hex[:8]}",
            "refund_amount": round(rng.uniform(200, 8000), 2),
            "currency": rng.choice(["INR", "USD", "EUR", "GBP", "AED"]),
        }
    elif et == "no_show":
        base["payload"] = {
            "pnr": pnr,
            "scheduled_departure": _ts(booking_date, rng),
        }
    elif et == "upgrade":
        from_class, to_class = rng.choice([("Y","J"), ("Y","F"), ("J","F"), ("M","Y")])
        base["payload"] = {
            "pnr": pnr,
            "from_class": from_class,
            "to_class":   to_class,
            "fare_diff":  round(rng.uniform(150, 3500), 2),
        }
    elif et == "seat_release":
        n = rng.randint(1, 4)
        base["payload"] = {
            "pnr": pnr,
            "released_seats": [f"{rng.randint(10,40)}{rng.choice('ABCDEF')}"
                               for _ in range(n)],
        }
    return base


def parse_dates(s: str) -> list[date]:
    """Parse '2026-05-01..2026-05-10' into a list of dates."""
    a, b = s.split("..")
    d0 = date.fromisoformat(a)
    d1 = date.fromisoformat(b)
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=10000,
                   help="number of events to generate")
    p.add_argument("--airlines", default="AI,EK,LH,SQ",
                   help="comma-separated airline codes")
    p.add_argument("--date-range", default="2026-05-01..2026-05-10",
                   help="inclusive date range, e.g. 2026-05-01..2026-05-10")
    p.add_argument("--event-types",
                   default="cancellation,refund,no_show,upgrade,seat_release",
                   help="comma-separated event types")
    p.add_argument("--out", required=True, help="output NDJSON path")
    args = p.parse_args()

    airlines = args.airlines.split(",")
    dates = parse_dates(args.date_range)
    event_types = args.event_types.split(",")

    rng = random.Random(20260719)

    with open(args.out, "w") as f:
        for _ in range(args.count):
            ev = make_event(rng, airlines, dates, event_types)
            f.write(json.dumps(ev, separators=(",", ":")) + "\n")

    size_kb = sum(1 for _ in open(args.out, "rb").read().splitlines()) and \
              __import__("os").path.getsize(args.out) / 1024
    print(f"✓ wrote {args.count:,} events to {args.out}  ({size_kb:.1f} KB)")
    print(f"  airlines:    {airlines}")
    print(f"  date range:  {dates[0]} → {dates[-1]} ({len(dates)} days)")
    print(f"  event types: {event_types}")
    print()
    print("Lab 3 push commands:")
    print()
    print("  # Strategy A — random PK (booking_id UUID)")
    print("  while IFS= read -r line; do")
    print('    PK=$(echo "$line" | jq -r .event_id)')
    print('    DATA=$(echo -n "$line" | base64)')
    print('    aws kinesis put-record --stream-name accelya-bookings-stream-$LEARNER \\')
    print('      --partition-key "$PK" --data "$DATA" --region $AWS_REGION')
    print(f'  done < {args.out}')
    print()
    print("  # Strategy B — composite (airline_code:booking_date)")
    print('  # Use put-records (batch) for throughput; one batch per PK:')
    print('  # see docs/lab-guides/module-7-labs.md Lab 3 step 3.')
    return 0


if __name__ == "__main__":
    sys.exit(main())
