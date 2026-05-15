"""
src/m5_test_validator/handler.py — Day 5 Lab 2 reference handler.

STANDALONE partial-batch demo. NOT part of the main pipeline.

Invocation model:
    SQS Event Source Mapping -> Lambda. event['Records'] is a list of messages.
    BatchSize 10, MaximumBatchingWindowInSeconds 5,
    FunctionResponseTypes ['ReportBatchItemFailures'].

Event in:
    { "Records": [
        { "messageId":   "<uuid>",
          "body":        "{\"file_key\":..., \"line_no\":..., \"row\":{...}, \"mode\"?:...}",
          "messageAttributes": {
              "error_type":   {"stringValue": "TransientError", "dataType":"String"},
              "replay_attempt": {"stringValue": "0", "dataType":"String"}
          }
        }, ...
    ] }

Return shape (the contract that drives partial-batch retries):
    { "batchItemFailures": [
        { "itemIdentifier": "<messageId of TRANSIENT failure only>" }
    ] }

Critical contract (from SQS PARTIAL-BATCH CONTEXT in .windsurfrules v2):
    - Row-level schema failures   -> QUARANTINE + ACK; NOT in batchItemFailures
    - Row-level business failures -> QUARANTINE + ACK; NOT in batchItemFailures
    - Idempotency duplicate skips -> ACK; NOT in batchItemFailures
    - TRANSIENT failures only     -> add to batchItemFailures (SQS will retry)
    - mode=force_transient        -> demo trigger; raises TransientError

Environment variables:
    STAGING_BUCKET             S3 bucket
    LEARNER                    learner name suffix
    IDEMP_TABLE                DynamoDB table for idempotency
    FORCE_TRANSIENT_ENABLED    'true' to honour mode=force_transient (default 'true');
                               Lab 3 toggles this to 'false' to demonstrate the fix.

Runtime: python3.12 · 512 MB · 10 s timeout · region ap-south-1.
"""
from __future__ import annotations

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
    SchemaError,
    TransientError,
)

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
s3 = boto3.client("s3", region_name=REGION)
ddb = boto3.client("dynamodb", region_name=REGION)

REQUIRED_FIELDS = {
    "settlement_id", "bsp_cycle", "airline_code", "pnr", "fare_class",
    "od_pair", "ticket_number", "issue_date", "fare_amount", "currency",
    "agency_iata", "source_system",
}


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def _claim(table: str, pk: str, ttl_days: int) -> bool:
    now = int(time.time())
    ttl = now + (ttl_days * 86_400)
    try:
        ddb.put_item(
            TableName=table,
            Item={"pk": {"S": pk}, "outcome": {"S": "claimed"},
                  "processed_at": {"N": str(now)}, "ttl": {"N": str(ttl)}},
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _validate_row(row: dict[str, Any], file_key: str, line_no: int) -> None:
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        raise SchemaError(
            f"Missing fields: {sorted(missing)}",
            file_key=file_key, line_no=line_no,
        )
    if not isinstance(row.get("fare_amount"), (int, float)):
        raise SchemaError(
            "fare_amount must be numeric",
            file_key=file_key, line_no=line_no,
        )


def _persist_validated(bucket: str, learner: str, row: dict[str, Any]) -> None:
    sid = row.get("settlement_id", "unknown")
    key = f"validated/{learner}/{row.get('bsp_cycle', 'unknown')}/{sid}.json"
    s3.put_object(
        Bucket=bucket, Key=key,
        Body=json.dumps(row, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )


def _persist_quarantine(bucket: str, learner: str, reason: str,
                        file_key: str, line_no: int, row: dict[str, Any],
                        detail: str, corr_id: str) -> None:
    safe = file_key.replace("/", "_")
    key = f"quarantine/{reason}/{learner}/{safe}:{line_no}.sidecar.json"
    sidecar = {
        "reason": reason, "source_file": file_key, "line_no": line_no,
        "correlation_id": corr_id, "validator_version": "m5-test-v1",
        "detail": detail, "original_record": row,
    }
    s3.put_object(
        Bucket=bucket, Key=key,
        Body=json.dumps(sidecar, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    corr_id = getattr(context, "aws_request_id", "no-corr-id")
    records = event.get("Records", [])

    bucket = _required_env("STAGING_BUCKET")
    learner = _required_env("LEARNER")
    table = _required_env("IDEMP_TABLE")
    force_transient_enabled = (
        os.environ.get("FORCE_TRANSIENT_ENABLED", "true").lower() == "true"
    )

    failures: list[dict[str, str]] = []

    for record in records:
        msg_id = record.get("messageId", "no-msg-id")
        try:
            payload = json.loads(record.get("body", "{}"))
        except json.JSONDecodeError as e:
            # Malformed body -> quarantine + ACK (not a transient failure)
            _persist_quarantine(
                bucket, learner, "malformed",
                "sqs/inline", 0, {"raw_body": record.get("body")},
                str(e), corr_id,
            )
            LOG.warning(json.dumps({
                "event": "row_quarantined", "reason": "malformed",
                "message_id": msg_id, "corr_id": corr_id,
            }))
            continue

        file_key = payload.get("file_key", "sqs/inline")
        line_no = int(payload.get("line_no", 0))
        row = payload.get("row", {})
        mode = payload.get("mode")

        # Demo trigger: forced transient
        if mode == "force_transient" and force_transient_enabled:
            LOG.warning(json.dumps({
                "event": "forced_transient", "message_id": msg_id, "corr_id": corr_id,
            }))
            failures.append({"itemIdentifier": msg_id})
            continue
            # NOTE: we don't raise; raising kills the WHOLE batch.

        # Row idempotency claim
        row_pk = f"row#{file_key}:{line_no}"
        if not _claim(table, row_pk, ttl_days=30):
            LOG.info(json.dumps({
                "event": "row_duplicate", "message_id": msg_id, "corr_id": corr_id,
            }))
            continue  # ACK; duplicate is not a failure

        # Schema validation
        try:
            _validate_row(row, file_key, line_no)
        except SchemaError as e:
            _persist_quarantine(
                bucket, learner, "schema_drift", file_key, line_no, row,
                str(e), corr_id,
            )
            LOG.warning(json.dumps({
                "event": "row_quarantined", "reason": "schema_drift",
                "message_id": msg_id, "corr_id": corr_id,
                "detail": str(e),
            }))
            continue  # ACK; quarantine is NOT a failure

        # Business idempotency
        biz_pk = f"business#{row.get('settlement_id', '')}"
        if not _claim(table, biz_pk, ttl_days=30):
            LOG.info(json.dumps({
                "event": "row_duplicate_business",
                "message_id": msg_id, "corr_id": corr_id,
            }))
            continue

        # Persist
        try:
            _persist_validated(bucket, learner, row)
            LOG.info(json.dumps({
                "event": "row_landed", "message_id": msg_id, "corr_id": corr_id,
                "settlement_id": row.get("settlement_id"),
            }))
        except ClientError as e:
            # Real transient infra failure -> partial-batch retry
            LOG.warning(json.dumps({
                "event": "row_transient", "message_id": msg_id, "corr_id": corr_id,
                "detail": str(e),
            }))
            failures.append({"itemIdentifier": msg_id})

    LOG.info(json.dumps({
        "event": "batch_done", "corr_id": corr_id,
        "total": len(records), "failures": len(failures),
    }))

    return {"batchItemFailures": failures}
