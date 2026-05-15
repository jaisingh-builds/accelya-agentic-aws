#!/usr/bin/env python3
"""
gen_test_batch.py — Day 5 Lab 2 helper.

Generates a 10-row SQS send-message-batch payload for the `m5-test-queue`.
Exactly ONE row is intentionally schema-broken (default: row 4, missing
required `fare_amount` field) so Demo A demonstrates: 9 validated, 1
quarantined, 0 batchItemFailures.

Usage:
    python3 -m scripts.gen_test_batch --rows 10 --poison-line 4 \\
        --out /tmp/m5-test-batch-sqs.json

Then:
    aws sqs send-message-batch \\
        --queue-url $TEST_QUEUE_URL \\
        --entries file:///tmp/m5-test-batch-sqs.json \\
        --region ap-south-1

The output JSON is in the shape `aws sqs send-message-batch` expects:
    [ { "Id": "msg-001", "MessageBody": "<json>", "MessageAttributes": {...} }, ... ]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _good_row(i: int) -> dict:
    return {
        "settlement_id": f"BSP-2026-W19-AI234-LAB2-{i:03d}",
        "bsp_cycle":     "2026-W19",
        "airline_code":  "AI",
        "pnr":           f"L2{i:04d}",
        "fare_class":    ["Y", "J", "F"][i % 3],
        "od_pair":       "BOM-LHR",
        "ticket_number": f"098-{9000000 + i:013d}",
        "issue_date":    "2026-05-09T11:42:00+05:30",
        "fare_amount":   2845.0 + i,
        "currency":      "INR",
        "agency_iata":   "14305820",
        "source_system": "BSP",
    }


def _poison_row(i: int) -> dict:
    """Schema-drift defect: removes `fare_amount` (required field)."""
    r = _good_row(i)
    r.pop("fare_amount", None)
    return r


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=10)
    p.add_argument("--poison-line", type=int, default=4,
                   help="1-based line number to inject schema defect into")
    p.add_argument("--out", required=True, help="output JSON path")
    p.add_argument("--file-key", default="sqs/lab2/test-batch.json")
    args = p.parse_args()

    entries = []
    for i in range(1, args.rows + 1):
        row = _poison_row(i) if i == args.poison_line else _good_row(i)
        body = {
            "file_key": args.file_key,
            "line_no":  i,
            "row":      row,
        }
        entries.append({
            "Id": f"msg-{i:03d}",
            "MessageBody": json.dumps(body, separators=(",", ":")),
            "MessageAttributes": {
                "error_type": {
                    "DataType": "String",
                    "StringValue": "None",
                },
                "replay_attempt": {
                    "DataType": "String",
                    "StringValue": "0",
                },
                "first_seen_at": {
                    "DataType": "String",
                    "StringValue": datetime.now(timezone.utc).isoformat(),
                },
            },
        })

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(entries, f, indent=2)

    print(f"✓ wrote {len(entries)} entries to {args.out}")
    print(f"  poisoned line: {args.poison_line} (missing fare_amount)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
