#!/usr/bin/env python3
"""
gen_m8_test_batch.py — Lab 2 test batch generator.

Produces an `events: [...]` payload suitable for `aws lambda invoke`-ing the
M8 producer. Mix of valid and deliberately poison records to exercise the
partial-batch + quarantine flow.

Usage:
    python3 -m scripts.gen_m8_test_batch \\
        --rows 10 \\
        --poison 2 \\
        --out /tmp/m8-test-batch.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import uuid
from datetime import datetime, timezone

random.seed(20260818)


def good_event(i: int) -> dict:
    return {
        "event_id":      str(uuid.uuid4()),
        "event_type":    "cancellation",
        "event_time":    "2026-05-09T14:45:23+00:00",
        "ingest_time":   datetime.now(timezone.utc).isoformat(),
        "airline_code":  random.choice(["AI", "EK", "LH", "SQ"]),
        "booking_date":  "2026-05-09",
        "pnr":           f"TEST{i:04d}",
        "source_system": "GDS",
        "payload": {
            "pnr":                    f"TEST{i:04d}",
            "cancel_reason_code":     random.choice(["WX", "PAX", "OPS", "MED"]),
            "cancellation_event_id":  f"CXL-{uuid.uuid4().hex[:8]}",
        },
    }


def poison_event(i: int) -> dict:
    """Validation-failing record. Two poison shapes alternating:
       - Missing required field (pnr)
       - Unknown event_type
    """
    base = good_event(i)
    if i % 2 == 0:
        base.pop("pnr", None)             # missing required field
    else:
        base["event_type"] = "unknown_xyz"  # unknown event_type
    return base


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=10)
    p.add_argument("--poison", type=int, default=2)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    if args.poison > args.rows:
        print("ERROR: poison count exceeds rows", file=sys.stderr)
        return 1

    n_good = args.rows - args.poison
    events: list[dict] = []
    for i in range(n_good):
        events.append(good_event(i))
    for i in range(args.poison):
        events.append(poison_event(i + n_good))

    random.shuffle(events)

    payload = {"events": events}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(payload, f)

    print(f"✓ wrote {args.rows} events ({n_good} valid + {args.poison} poison) to {args.out}")
    print()
    print("Invoke producer with:")
    print(f"  aws lambda invoke \\")
    print(f"    --function-name accelya-producer-$LEARNER \\")
    print(f"    --cli-binary-format raw-in-base64-out \\")
    print(f"    --payload file://{args.out} \\")
    print(f"    --region $AWS_REGION /tmp/m8-producer-out.json")
    print(f"  cat /tmp/m8-producer-out.json | python3 -m json.tool")
    return 0


if __name__ == "__main__":
    sys.exit(main())
