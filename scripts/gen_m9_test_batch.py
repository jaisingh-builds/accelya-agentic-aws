#!/usr/bin/env python3
"""
gen_m9_test_batch.py — Day 9 Lab 3 test batch generator.

Produces an `events: [...]` payload for the M8 producer with deliberately-
calibrated features that the cancel-risk model maps to high or low
confidence — so we can prove the ASL HasLowConfidence Choice routes
correctly.

Calibration assumes the reference logistic-regression model from
src/m9_model/inference.py (trained in-container deterministically):
  - High-confidence inputs: extreme features (large fare, immediate refund,
    or no refund) → model outputs confidence > 0.7
  - Low-confidence inputs: ambiguous features (mid-range everything) →
    model outputs confidence < 0.7

Usage:
    python3 -m scripts.gen_m9_test_batch \\
        --high-conf 7 --low-conf 3 \\
        --out /tmp/m9-10-events.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone


def good_event(i: int, conf_class: str) -> dict:
    """conf_class: 'high' or 'low'. Features tuned to the lab model."""
    if conf_class == "high":
        # Sharp, discriminative features
        fare_amount = 4500.0 if i % 2 == 0 else 250.0   # extreme either way
        refund_lag_hours = 0.5 if i % 2 == 0 else 168.0  # immediate or week-late
        prior_cancels = 0 if i % 2 == 0 else 5           # clean or repeat-offender
    else:  # low
        # Ambiguous mid-range features
        fare_amount = 2200.0 + (i * 50)                  # near average
        refund_lag_hours = 12.0 + (i * 2)                # neither immediate nor late
        prior_cancels = 1                                # ambiguous prior

    base = {
        "event_id":      str(uuid.uuid4()),
        "event_type":    "cancellation",
        "event_time":    "2026-05-09T14:45:23+00:00",
        "ingest_time":   datetime.now(timezone.utc).isoformat(),
        "airline_code":  "AI",
        "booking_date":  "2026-05-09",
        "pnr":           f"M9{i:04d}",
        "source_system": "GDS",
        "payload": {
            "pnr":                   f"M9{i:04d}",
            "cancel_reason_code":    "WX",
            "cancellation_event_id": f"CXL-M9-{i:04d}",
            # Predict-model features (flat at payload level for wrapper consumption)
            "booking_id":            f"BK-M9-{i:04d}",
            "fare_amount":           fare_amount,
            "refund_lag_hours":      refund_lag_hours,
            "prior_cancels":         prior_cancels,
        },
        # Also flat for direct-invoke convenience (predict handler reads both shapes)
        "booking_id":       f"BK-M9-{i:04d}",
        "fare_amount":      fare_amount,
        "refund_lag_hours": refund_lag_hours,
        "prior_cancels":    prior_cancels,
        "_expected_conf":   conf_class,
    }
    return base


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--high-conf", type=int, default=7,
                   help="number of high-confidence events to generate")
    p.add_argument("--low-conf", type=int, default=3,
                   help="number of low-confidence events to generate")
    p.add_argument("--out", required=True, help="output JSON path")
    args = p.parse_args()

    events = []
    for i in range(args.high_conf):
        events.append(good_event(i, "high"))
    for i in range(args.low_conf):
        events.append(good_event(args.high_conf + i, "low"))

    payload = {"events": events}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(payload, f)

    print(f"✓ wrote {len(events)} events to {args.out}")
    print(f"  high-conf: {args.high_conf} (expected confidence >= 0.7)")
    print(f"  low-conf:  {args.low_conf} (expected confidence < 0.7)")
    print()
    print("Send via M8 producer:")
    print(f"  aws lambda invoke \\")
    print(f"    --function-name accelya-producer-$LEARNER \\")
    print(f"    --cli-binary-format raw-in-base64-out \\")
    print(f"    --payload file://{args.out} \\")
    print(f"    --region $AWS_REGION /tmp/m9-producer-out.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
