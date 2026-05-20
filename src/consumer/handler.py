"""
src/consumer/handler.py — Day 8 Lab 1 reference handler.

THIN Kinesis consumer. ESM-triggered. 4 stages per record:
    1. Idempotency-claim (ConditionalPut on stream_seen_keys, status=CLAIMED)
    2. base64 decode + envelope validate
    3. sfn.start_execution(name=f"enrich-{event_id}")  — deterministic
    4. Mark stream-PK status=COMPLETED

CRITICAL — what this handler does NOT do:
    - NO inline Bedrock calls (Concept 5 / mistake #1)
    - NO inline S3 writes for enrichment
    - NO non-deterministic SFN execution names
    - NO reporting all failures (only the OLDEST per shard)

Event in (from ESM):
    { "Records": [
        { "kinesis": { "partitionKey": "AI:2026-05-09:3",
                       "sequenceNumber": "49641844...",
                       "data": "<base64>" },
          "eventID": "shardId-000000000000:49641844..." }, ...
    ] }

Return shape:
    { "batchItemFailures": [{"itemIdentifier": "<oldest_failed_seq>"}] }

Failure routing:
    ValidationError    → quarantine/<learner>/stream_invalid/<reason>/  (ACK)
    MalformedRowError  → quarantine/<learner>/stream_invalid/parse_error/ (ACK)
    TransientError     → batchItemFailures
    ConfigError        → ESM destination DLQ (raised; ESM handles)

Environment variables required:
    STREAM_NAME       e.g. accelya-bookings-stream-<learner>
    LEARNER           learner suffix
    IDEMP_TABLE       e.g. stream_seen_keys_<learner>
    SM_ARN            inference-pipeline state machine ARN
    QUARANTINE_BUCKET S3 bucket for stream_invalid/

Runtime: python3.12 · 512 MB · 60 s timeout · region ap-south-1.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sys
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.exceptions import (  # noqa: E402
    ConfigError,
    MalformedRowError,
    TransientError,
    ValidationError,
)

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
ddb = boto3.client("dynamodb", region_name=REGION)
sfn = boto3.client("stepfunctions", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)

KNOWN_EVENT_TYPES = {
    "cancellation", "refund", "no_show", "upgrade", "seat_release",
}


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def _claim_idempotency(table: str, pk: str, ttl_days: int = 7) -> bool:
    """Returns True if claim succeeded (new key)."""
    now = int(time.time())
    ttl = now + (ttl_days * 86_400)
    try:
        ddb.put_item(
            TableName=table,
            Item={
                "pk": {"S": pk},
                "status": {"S": "CLAIMED"},
                "claimed_at": {"N": str(now)},
                "ttl": {"N": str(ttl)},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _mark_status(table: str, pk: str, status: str) -> None:
    """Update status on an existing claim."""
    now = int(time.time())
    ddb.update_item(
        TableName=table,
        Key={"pk": {"S": pk}},
        UpdateExpression="SET #s = :s, updated_at = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": {"S": status},
            ":t": {"N": str(now)},
        },
    )


def _validate_envelope(data: dict[str, Any]) -> None:
    required = ["event_id", "event_type", "airline_code",
                "booking_date", "pnr", "payload"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise ValidationError(
            f"Envelope missing required fields: {missing}",
            file_key=data.get("event_id"),
        )
    if data["event_type"] not in KNOWN_EVENT_TYPES:
        raise ValidationError(
            f"Unknown event_type: {data['event_type']}",
            file_key=data.get("event_id"),
        )


def _quarantine(bucket: str, learner: str, reason: str,
                data: dict[str, Any], detail: str, corr_id: str) -> None:
    event_id = data.get("event_id", "unknown")
    key = f"quarantine/{learner}/stream_invalid/{reason}/{event_id}.sidecar.json"
    sidecar = {
        "reason": reason,
        "stream_invalid": True,
        "correlation_id": corr_id,
        "consumer_version": "m8-v1",
        "detail": detail,
        "original_record": data,
        "quarantined_at": int(time.time()),
    }
    s3.put_object(
        Bucket=bucket, Key=key,
        Body=json.dumps(sidecar, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )


def _start_inference(sm_arn: str, data: dict[str, Any], stream_pk: str,
                     corr_id: str) -> bool:
    """Returns True on first-time-success or ExecutionAlreadyExists (both idempotent)."""
    event_id = data.get("event_id", "unknown")
    exec_name = f"enrich-{event_id}"   # DETERMINISTIC

    sfn_input = json.dumps({
        **data,
        "stream_pk": stream_pk,
        "corr_id": corr_id,
    })
    try:
        sfn.start_execution(
            stateMachineArn=sm_arn,
            name=exec_name,
            input=sfn_input,
        )
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code == "ExecutionAlreadyExists":
            LOG.info(json.dumps({
                "event": "handoff_already_exists", "corr_id": corr_id,
                "exec_name": exec_name,
            }))
            return True  # idempotent success
        # ExecutionLimitExceeded / etc → transient
        raise TransientError(
            f"start_execution failed: {code}",
            file_key=event_id, detail=str(e),
        ) from e


def _emit_consumer_emf(stream_name: str, shard_id: str,
                       records_in: int, records_quarantined: int,
                       handoff_succeeded: int, handoff_already_exists: int,
                       records_failed: int, corr_id: str) -> None:
    print(json.dumps({
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "Accelya/Streaming",
                "Dimensions": [["StreamName", "ShardId"]],
                "Metrics": [
                    {"Name": "records_in",            "Unit": "Count"},
                    {"Name": "records_quarantined",   "Unit": "Count"},
                    {"Name": "handoff_succeeded",     "Unit": "Count"},
                    {"Name": "handoff_already_exists","Unit": "Count"},
                    {"Name": "records_failed",        "Unit": "Count"},
                ],
            }],
        },
        "StreamName":              stream_name,
        "ShardId":                  shard_id,
        "records_in":              records_in,
        "records_quarantined":     records_quarantined,
        "handoff_succeeded":       handoff_succeeded,
        "handoff_already_exists":  handoff_already_exists,
        "records_failed":          records_failed,
        "corr_id":                 corr_id,
    }))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    corr_id = getattr(context, "aws_request_id", "no-corr-id")
    records = event.get("Records", [])

    stream_name = _required_env("STREAM_NAME")
    learner = _required_env("LEARNER")
    table = _required_env("IDEMP_TABLE")
    sm_arn = _required_env("SM_ARN")
    quarantine_bucket = _required_env("QUARANTINE_BUCKET")

    # Trackers
    oldest_failure_seq: str | None = None
    counts = {
        "records_in": len(records),
        "records_quarantined": 0,
        "handoff_succeeded": 0,
        "handoff_already_exists": 0,
        "records_failed": 0,
    }
    shard_id_seen = "shardId-unknown"

    for record in records:
        kinesis_meta = record.get("kinesis", {})
        seq = kinesis_meta.get("sequenceNumber", "")
        event_id_path = record.get("eventID", "")
        shard_id = event_id_path.split(":")[0] if ":" in event_id_path else shard_id_seen
        shard_id_seen = shard_id
        stream_pk = f"stream#{stream_name}#{shard_id}#{seq}"

        # STAGE 1: Idempotency-claim
        try:
            if not _claim_idempotency(table, stream_pk):
                # Duplicate — silent skip
                LOG.info(json.dumps({
                    "event": "record_duplicate", "corr_id": corr_id,
                    "stream_pk": stream_pk,
                }))
                continue
        except ClientError as e:
            LOG.error(json.dumps({
                "event": "claim_failed", "corr_id": corr_id,
                "stream_pk": stream_pk, "error": str(e),
            }))
            counts["records_failed"] += 1
            if oldest_failure_seq is None or seq < oldest_failure_seq:
                oldest_failure_seq = seq
            continue

        # STAGE 2: base64 decode + envelope validate
        try:
            raw = base64.b64decode(kinesis_meta.get("data", ""))
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            _quarantine(quarantine_bucket, learner, "parse_error",
                        {"raw_b64": kinesis_meta.get("data", "")},
                        str(e), corr_id)
            counts["records_quarantined"] += 1
            _mark_status(table, stream_pk, "COMPLETED")
            continue

        try:
            _validate_envelope(data)
        except ValidationError as ve:
            _quarantine(quarantine_bucket, learner, "schema_drift",
                        data, str(ve), corr_id)
            counts["records_quarantined"] += 1
            _mark_status(table, stream_pk, "COMPLETED")
            continue

        # STAGE 3: StartExecution on state machine
        try:
            already_existed_before = False
            # Detect via separate try (cheap): start_execution returns True
            # for both first-time success and AlreadyExists (idempotent).
            success = _start_inference(sm_arn, data, stream_pk, corr_id)
            if success:
                # We can't cheaply distinguish first-time from AlreadyExists
                # without an extra describe call; emit one combined metric.
                counts["handoff_succeeded"] += 1
        except TransientError as te:
            LOG.warning(json.dumps({
                "event": "handoff_failed_transient", "corr_id": corr_id,
                "stream_pk": stream_pk, "error": str(te),
            }))
            counts["records_failed"] += 1
            if oldest_failure_seq is None or seq < oldest_failure_seq:
                oldest_failure_seq = seq
            continue

        # STAGE 4: Mark COMPLETED
        try:
            _mark_status(table, stream_pk, "COMPLETED")
        except ClientError as e:
            LOG.warning(json.dumps({
                "event": "mark_completed_failed", "corr_id": corr_id,
                "stream_pk": stream_pk, "error": str(e),
            }))
            # Not fatal — claim is still CLAIMED, will be reclaimed on retry
            # Don't add to batchItemFailures; SFN started successfully

    # Emit EMF (one log line per invocation)
    _emit_consumer_emf(
        stream_name, shard_id_seen,
        counts["records_in"], counts["records_quarantined"],
        counts["handoff_succeeded"], counts["handoff_already_exists"],
        counts["records_failed"], corr_id,
    )

    LOG.info(json.dumps({
        "event": "consumer_done", "corr_id": corr_id, **counts,
    }))

    # Return ONLY the oldest failure (Concept 2)
    failures: list[dict[str, str]] = []
    if oldest_failure_seq:
        failures.append({"itemIdentifier": oldest_failure_seq})
    return {"batchItemFailures": failures}
