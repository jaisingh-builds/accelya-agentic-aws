"""
tests/integration_test.py — Day 11 end-to-end integration test.

Run by the `integration-test` CI stage AFTER deploy-sandbox successfully
created accelya-app-<branch-slug>. Sends BOTH a booking event AND a
cancellation event through the pipeline, asserts both reach the settlement
output in S3 with correct deltas.

Capstone (Day 12) reuses this test verbatim.

Usage (CI):
    python3 tests/integration_test.py --learner $CI_COMMIT_REF_SLUG \\
                                       --region $AWS_REGION

Usage (local):
    python3 tests/integration_test.py --learner trainer

Exit codes:
    0  → both events reached settlement output with correct deltas
    1  → assertion failed (test reported in /tmp/integration-results.json)
    2  → infrastructure error (AWS API failure, stack missing, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


# ──────────────────────────────────────────────────────────────────────────
# Synthetic events (one of each type)
# ──────────────────────────────────────────────────────────────────────────
def booking_event(corr_id: str) -> dict:
    return {
        "event_id":      corr_id,
        "event_type":    "booking",
        "event_time":    datetime.now(timezone.utc).isoformat(),
        "airline_code":  "AI",
        "source_system": "INTEGRATION_TEST",
        "pnr":           "ITEST-BOOK",
        "booking_date":  datetime.now(timezone.utc).date().isoformat(),
        "correlation_id": corr_id,
        "payload": {
            "pnr":                "ITEST-BOOK",
            "fare_class":         "Saver",
            "origin_destination": "BOM-LHR",
            "fare_break":         "BOM-DEL-LHR",
            "ticket_number":      "098-ITEST-001",
            "fare_amount":        55000.0,
            "currency":           "INR",
            "agent_code":         "AGT-INT-TEST",
            "payment_method":     "card",
            "passenger_count":    1,
        },
    }


def cancellation_event(corr_id: str) -> dict:
    return {
        "event_id":      corr_id,
        "event_type":    "cancellation",
        "event_time":    datetime.now(timezone.utc).isoformat(),
        "airline_code":  "AI",
        "source_system": "INTEGRATION_TEST",
        "pnr":           "ITEST-CXL",
        "booking_date":  datetime.now(timezone.utc).date().isoformat(),
        "correlation_id": corr_id,
        "payload": {
            "pnr":                    "ITEST-CXL",
            "fare_class":             "Saver",
            "origin_destination":     "BOM-LHR",
            "fare_break":             "BOM-DEL-LHR",
            "ticket_number":          "098-ITEST-002",
            "cancellation_event_id":  "CXL-INT-TEST-001",
            "cancel_reason_code":     "VOL",
            "before_or_after_dep":    "BEFORE",
            "no_show":                False,
            "fare_amount":            55000.0,
            "refund_lag_hours":       2.5,
            "prior_cancels":          0,
            "booking_id":             "BK-ITEST",
        },
        # Flat for direct-invoke convenience (producer reads both shapes)
        "booking_id":       "BK-ITEST",
        "fare_amount":      55000.0,
        "refund_lag_hours": 2.5,
        "prior_cancels":    0,
    }


# ──────────────────────────────────────────────────────────────────────────
# Pipeline interaction
# ──────────────────────────────────────────────────────────────────────────
def submit_event(lambda_client, learner: str, event: dict) -> None:
    """POST a single event to the producer Lambda."""
    payload = json.dumps({"events": [event]}).encode("utf-8")
    resp = lambda_client.invoke(
        FunctionName=f"accelya-producer-{learner}",
        InvocationType="RequestResponse",
        Payload=payload,
    )
    if resp.get("StatusCode") != 200 or "FunctionError" in resp:
        raise RuntimeError(f"producer invoke failed: status={resp.get('StatusCode')} "
                           f"error={resp.get('FunctionError')} "
                           f"payload={resp['Payload'].read().decode()[:500]}")


def wait_for_settlement(s3_client, bucket: str, learner: str, corr_id: str,
                        event_type: str, timeout_s: int = 180) -> dict:
    """
    Poll s3://bucket/enriched/<learner>/event_type=<type>/... for our record.

    The Day-11 capstone settlement output is at:
        s3://<bucket>/settlement/<learner>/event_type=<type>/<corr_id>.json

    For pre-capstone (Day 11 unit-integration), we accept either path.
    """
    deadline = time.time() + timeout_s
    prefixes = [
        f"settlement/{learner}/event_type={event_type}/",
        f"enriched/{learner}/event_type={event_type}/",
        f"enriched/{learner}/",   # fallback if event_type not partitioned yet
    ]

    while time.time() < deadline:
        for prefix in prefixes:
            try:
                resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=200)
            except ClientError as e:
                if e.response["Error"]["Code"] in ("NoSuchBucket", "AccessDenied"):
                    raise
                continue
            for obj in resp.get("Contents", []):
                # Read each object; look for correlation_id match
                try:
                    body = s3_client.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
                    if corr_id.encode() in body:
                        # parse — might be gzip JSONL or plain JSON
                        if obj["Key"].endswith(".gz"):
                            import gzip
                            text = gzip.decompress(body).decode("utf-8")
                        else:
                            text = body.decode("utf-8")
                        for line in text.splitlines():
                            try:
                                rec = json.loads(line)
                                if rec.get("correlation_id") == corr_id:
                                    return rec
                            except json.JSONDecodeError:
                                continue
                except ClientError:
                    continue
        time.sleep(5)

    raise TimeoutError(f"No settlement record for {corr_id} ({event_type}) after {timeout_s}s")


# ──────────────────────────────────────────────────────────────────────────
# Main test
# ──────────────────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--learner", required=True)
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "ap-south-1"))
    p.add_argument("--bucket", default="accelya-airline-data-ap-south-1")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--out", default="/tmp/integration-results.json")
    args = p.parse_args()

    booking_corr = f"itest-book-{uuid.uuid4().hex[:8]}"
    cancel_corr = f"itest-cxl-{uuid.uuid4().hex[:8]}"

    lambda_client = boto3.client("lambda", region_name=args.region)
    s3_client = boto3.client("s3", region_name=args.region)

    results: dict[str, object] = {
        "learner":   args.learner,
        "region":    args.region,
        "started":   datetime.now(timezone.utc).isoformat(),
        "booking":   {"corr_id": booking_corr, "submitted": False, "received": False},
        "cancellation": {"corr_id": cancel_corr, "submitted": False, "received": False},
    }

    try:
        # 1. Submit both events
        print(f"[1/3] Submitting booking event {booking_corr} ...")
        submit_event(lambda_client, args.learner, booking_event(booking_corr))
        results["booking"]["submitted"] = True

        print(f"[2/3] Submitting cancellation event {cancel_corr} ...")
        submit_event(lambda_client, args.learner, cancellation_event(cancel_corr))
        results["cancellation"]["submitted"] = True

        # 2. Wait for both to reach settlement output (parallel-ish via two waits)
        print(f"[3/3] Waiting for settlement records (timeout {args.timeout}s each) ...")
        booking_rec = wait_for_settlement(
            s3_client, args.bucket, args.learner, booking_corr,
            event_type="booking", timeout_s=args.timeout,
        )
        results["booking"]["received"] = True
        results["booking"]["record"] = booking_rec

        cancel_rec = wait_for_settlement(
            s3_client, args.bucket, args.learner, cancel_corr,
            event_type="cancellation", timeout_s=args.timeout,
        )
        results["cancellation"]["received"] = True
        results["cancellation"]["record"] = cancel_rec

        # 3. Assertions on settlement deltas
        booking_delta = booking_rec.get("settlement_delta", 0)
        cancel_delta = cancel_rec.get("settlement_delta", 0)
        assert booking_delta > 0, f"Booking settlement_delta should be POSITIVE, got {booking_delta}"
        assert cancel_delta < 0, f"Cancellation settlement_delta should be NEGATIVE, got {cancel_delta}"

        results["status"] = "PASS"
        results["finished"] = datetime.now(timezone.utc).isoformat()
        print(f"✓ Integration test PASSED ({booking_corr} + {cancel_corr})")
        return 0

    except AssertionError as e:
        results["status"] = "FAIL"
        results["error"] = f"AssertionError: {e}"
        print(f"✗ FAIL: {e}")
        return 1
    except (ClientError, RuntimeError, TimeoutError) as e:
        results["status"] = "INFRA_ERROR"
        results["error"] = f"{type(e).__name__}: {e}"
        print(f"✗ INFRA ERROR: {e}")
        return 2
    finally:
        with open(args.out, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"  Results written to {args.out}")


if __name__ == "__main__":
    sys.exit(main())
