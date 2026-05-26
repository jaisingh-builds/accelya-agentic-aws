"""
src/producer/handler.py — Day 8 Lab 1 reference handler.

Bulk PutRecords producer for cancellation/refund/no_show/upgrade/seat_release
events. Partition key composite with PNR hash bucket for per-PNR ordering.

Invocation model:
    Manual invoke today (aws lambda invoke) with a batch of events.
    Day 11 may wire as an EventBridge or API Gateway integration.

Event in:
    { "events": [ <envelope>, <envelope>, ... ] }   # ≤500 per call

Return shape:
    { "submitted_count": <int>,
      "failed_count":    <int>,
      "failed_records":  [
          { "event_id": "...", "error_code": "validation|PTEx|service",
            "error_message": "..." }, ...
      ] }

PK strategy (high-volume tier):
    f"{airline_code}:{booking_date}:{bucket_hash(pnr) % 8}"
    — preserves per-PNR ordering within hash bucket

Failure handling:
    ValidationError      → failed_records (NOT submitted)
    PutRecords FailedRecordCount > 0 → retry by INDEX with backoff+jitter, ≤5

Environment variables required:
    STREAM_NAME    e.g. accelya-bookings-stream-<learner>

Runtime: python3.12 · 512 MB · 60 s timeout · region ap-south-1.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import random
import sys
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.exceptions import ConfigError, ValidationError  # noqa: E402

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
kinesis = boto3.client("kinesis", region_name=REGION)

MAX_RETRIES = 5
MAX_BATCH = 500
# Day-11 Path-A widening: booking added so the same producer handles both
# halves of the integration test (booking + cancellation flow). Original
# Day-9 producer was cancellation-events-only because the stream was named
# 'cancellation-events-<learner>' — the stream now carries both event_types
# (routed downstream by event_type in the consumer/SFN).
KNOWN_EVENT_TYPES = {
    "booking", "cancellation", "refund", "no_show", "upgrade", "seat_release",
}


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def _bucket_hash(s: str) -> int:
    """Stable hash for PNR → 0..7 bucket.

    MD5 here is a PARTITIONING HASH for Kinesis bucket selection, not security.
    Deterministic PNR → bucket mapping preserves per-PNR ordering on shard
    placement; cryptographic strength is irrelevant. `usedforsecurity=False`
    (Python 3.9+) signals intent so bandit B324 doesn't flag.
    """
    return int(hashlib.md5(s.encode(), usedforsecurity=False).hexdigest(), 16)


def _partition_key(event: dict[str, Any]) -> str:
    """Composite PK preserving per-PNR ordering within a hash bucket."""
    airline = event["airline_code"]
    booking_date = event["booking_date"]
    pnr = event.get("pnr", "")
    bucket = _bucket_hash(pnr) % 8 if pnr else 0
    return f"{airline}:{booking_date}:{bucket}"


def _validate_envelope(e: dict[str, Any]) -> None:
    required = ["event_id", "event_type", "airline_code",
                "booking_date", "pnr", "payload"]
    missing = [k for k in required if not e.get(k)]
    if missing:
        raise ValidationError(
            f"Envelope missing required fields: {missing}",
            file_key=e.get("event_id"),
        )
    if e["event_type"] not in KNOWN_EVENT_TYPES:
        raise ValidationError(
            f"Unknown event_type: {e['event_type']}",
            file_key=e.get("event_id"),
        )


def _emit_emf(stream_name: str, airline_code: str,
              records_in: int, records_failed: int,
              retry_count: int, corr_id: str) -> None:
    """Emit single EMF log line — CloudWatch extracts metrics server-side."""
    print(json.dumps({
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "Accelya/Streaming",
                "Dimensions": [["stream_name", "airline_code"]],
                "Metrics": [
                    {"Name": "records_in",      "Unit": "Count"},
                    {"Name": "records_failed",  "Unit": "Count"},
                    {"Name": "retry_count",     "Unit": "Count"},
                ],
            }],
        },
        "stream_name":    stream_name,
        "airline_code":   airline_code,
        "records_in":     records_in,
        "records_failed": records_failed,
        "retry_count":    retry_count,
        "corr_id":        corr_id,
    }))


def _put_records_with_retry(stream_name: str,
                            records: list[dict[str, Any]],
                            corr_id: str) -> tuple[int, list[dict[str, Any]]]:
    """PutRecords with backoff+jitter retry on per-record failures.

    Returns (succeeded_count, failed_records_list).
    Retries by INDEX — re-submits only the still-failing records.
    """
    attempt = 0
    pending = records[:]
    failed_final: list[dict[str, Any]] = []
    succeeded = 0

    while pending and attempt < MAX_RETRIES:
        try:
            resp = kinesis.put_records(StreamName=stream_name, Records=pending)
        except ClientError as e:
            # Whole-call failure — retry the entire pending batch
            attempt += 1
            sleep_s = (2 ** attempt) * random.uniform(0.5, 1.5)
            LOG.warning(json.dumps({
                "event": "put_records_call_failed", "corr_id": corr_id,
                "error": type(e).__name__, "detail": str(e),
                "attempt": attempt, "sleep_s": round(sleep_s, 2),
            }))
            time.sleep(sleep_s)
            continue

        # Per-record outcomes
        still_failing: list[dict[str, Any]] = []
        new_failed: list[dict[str, Any]] = []
        for i, r in enumerate(resp["Records"]):
            if "ErrorCode" not in r:
                succeeded += 1
                continue
            err = r.get("ErrorCode", "Unknown")
            if err == "ProvisionedThroughputExceededException":
                still_failing.append(pending[i])
            else:
                # Other service-level failure — don't retry
                new_failed.append({
                    "error_code": err,
                    "error_message": r.get("ErrorMessage", ""),
                })

        failed_final.extend(new_failed)
        # Always advance `pending` to just the records still needing retry —
        # if empty, the while loop's condition exits naturally.
        pending = still_failing
        if not pending:
            break

        attempt += 1
        sleep_s = (2 ** attempt) * random.uniform(0.5, 1.5)
        LOG.warning(json.dumps({
            "event": "put_records_retry", "corr_id": corr_id,
            "still_failing": len(still_failing), "attempt": attempt,
            "sleep_s": round(sleep_s, 2),
        }))
        time.sleep(sleep_s)

    # Anything still pending after MAX_RETRIES → final failure
    if pending:
        for p in pending:
            failed_final.append({
                "error_code": "ProvisionedThroughputExceededException",
                "error_message": f"Retried {MAX_RETRIES} times, gave up",
            })

    return succeeded, failed_final


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    corr_id = getattr(context, "aws_request_id", "no-corr-id")
    events_in = event.get("events", [])
    stream_name = _required_env("STREAM_NAME")

    LOG.info(json.dumps({
        "event": "producer_start", "corr_id": corr_id,
        "events_count": len(events_in), "stream_name": stream_name,
    }))

    if len(events_in) > MAX_BATCH:
        raise ValidationError(
            f"Batch too large: {len(events_in)} > {MAX_BATCH}",
            detail=f"PutRecords max is {MAX_BATCH}",
        )

    # Pre-submit validation
    failed_records: list[dict[str, Any]] = []
    valid_records: list[dict[str, Any]] = []
    valid_originals: list[dict[str, Any]] = []
    for e in events_in:
        try:
            _validate_envelope(e)
        except ValidationError as ve:
            failed_records.append({
                "event_id": e.get("event_id"),
                "error_code": "validation",
                "error_message": str(ve),
            })
            continue
        valid_records.append({
            "Data": json.dumps(e).encode("utf-8"),
            "PartitionKey": _partition_key(e),
        })
        valid_originals.append(e)

    # Bulk PutRecords with retry
    submitted_count = 0
    if valid_records:
        submitted_count, retry_failed = _put_records_with_retry(
            stream_name, valid_records, corr_id,
        )
        # Annotate failed records back with event_id (we lost the binding to
        # original index across retries — best-effort by position).
        for i, f in enumerate(retry_failed):
            f["event_id"] = (
                valid_originals[i].get("event_id")
                if i < len(valid_originals) else None
            )
            failed_records.append(f)

    # EMF
    # Pick first airline from the input batch (or 'mixed' if not present)
    airline_for_metric = (
        events_in[0].get("airline_code", "mixed") if events_in else "mixed"
    )
    _emit_emf(stream_name, airline_for_metric, len(events_in),
              len(failed_records), 0, corr_id)

    LOG.info(json.dumps({
        "event": "producer_done", "corr_id": corr_id,
        "submitted_count": submitted_count,
        "failed_count": len(failed_records),
    }))

    return {
        "submitted_count": submitted_count,
        "failed_count": len(failed_records),
        "failed_records": failed_records,
    }
