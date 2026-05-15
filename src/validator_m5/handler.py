"""
src/validator_m5/handler.py — Day 5 Lab 1 reference handler.

Stage 2 of the validator-pipeline state machine. Chunk-aware.

(Naming note: src/validator/handler.py is reserved for the Day 2 starter
 Lambda with a direct S3 trigger. This M5 handler has a different invocation
 contract — ASL Task Map iteration — so it lives in its own folder.)

Invocation model:
    Step Functions Map iterator -> Lambda. One invocation per chunk.
    The Map state's ItemSelector builds the event:
        { chunk_key: <one chunk path>,
          file_key:  <parent context>,
          file_sha256: <parent context> }

Event in:
    { "chunk_key":   "staging/<learner>/<sha>/chunk-0001.jsonl",
      "file_key":    "raw/synthetic/m4-failures/01-schema-drift.json",
      "file_sha256": "<64-hex>" }

Return shape:
    { "validated":   <int>,
      "quarantined": <int>,
      "duplicate":   <int>,
      "chunk_key":   "<input>",
      "file_key":    "<input>",
      "file_sha256": "<input>" }

Per-row contract (from ASL CHUNK CONTEXT in .windsurfrules v2):
    1. Claim row#<file_key>:<line_no>      (TTL 30d)  -> skip if duplicate
    2. Schema-validate (raises SchemaError)
    3. Claim business#<settlement_id>      (TTL 30d)  -> skip if duplicate
    4. Persist row to validated/<learner>/

Failure routes (raised to ASL Catch):
    ValidationError  -> QuarantineSchemaDrift   when >50% rows fail in this chunk
    ConfigError      -> NotifyOps               env var missing

Idempotency: row# + business# (validator owns these two prefixes).
             file# + canonical# are owned by the lander.

Environment variables required:
    STAGING_BUCKET     S3 bucket (where chunks live + validated/ lands)
    LEARNER            learner name suffix
    IDEMP_TABLE        DynamoDB table name (e.g. idempotency_keys_<learner>)

Runtime: python3.12 · 1024 MB · 60 s timeout · region ap-south-1.
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
    ValidationError,
)

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
s3 = boto3.client("s3", region_name=REGION)
ddb = boto3.client("dynamodb", region_name=REGION)

# Required fields per Day 4 schema lock
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


def _claim_idempotency(table: str, pk: str, outcome: str, ttl_days: int) -> bool:
    """ConditionalPut on a guard key. Returns True if claim succeeded (new key).
    Returns False if key already existed (duplicate path).
    """
    now = int(time.time())
    ttl = now + (ttl_days * 86_400)
    try:
        ddb.put_item(
            TableName=table,
            Item={
                "pk": {"S": pk},
                "outcome": {"S": outcome},
                "processed_at": {"N": str(now)},
                "ttl": {"N": str(ttl)},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _validate_schema(row: dict[str, Any], line_no: int, file_key: str) -> None:
    """Programme schema check. Raise SchemaError on first defect."""
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        raise SchemaError(
            f"Missing required fields: {sorted(missing)}",
            file_key=file_key, line_no=line_no,
            detail=f"missing={sorted(missing)}",
        )
    if not isinstance(row.get("fare_amount"), (int, float)):
        raise SchemaError(
            "fare_amount must be numeric",
            file_key=file_key, line_no=line_no,
            detail=f"got_type={type(row['fare_amount']).__name__}",
        )


def _business_key(row: dict[str, Any]) -> str:
    """Settlement_id is the natural business key; fall back to composite."""
    sid = row.get("settlement_id")
    if sid:
        return str(sid)
    return "|".join([
        str(row.get("ticket_number", "")),
        str(row.get("bsp_cycle", "")),
        str(row.get("agency_iata", "")),
        str(row.get("fare_amount", "")),
    ])


def _persist_validated(bucket: str, learner: str, settlement_date: str,
                       chunk_id: str, rows: list[dict[str, Any]]) -> str:
    key = f"validated/{learner}/{settlement_date}/{chunk_id}.jsonl"
    body = "\n".join(json.dumps(r, separators=(",", ":")) for r in rows).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/x-ndjson")
    return key


def _persist_quarantine(bucket: str, learner: str, reason: str, file_key: str,
                        line_no: int, row: dict[str, Any], detail: str,
                        corr_id: str) -> str:
    """Write quarantine sidecar JSON. Distinct path per reason."""
    safe_name = file_key.replace("/", "_")
    sidecar_key = f"quarantine/{reason}/{learner}/{safe_name}:{line_no}.sidecar.json"
    sidecar = {
        "reason": reason,
        "source_file": file_key,
        "line_no": line_no,
        "correlation_id": corr_id,
        "validator_version": "m5-v1",
        "detail": detail,
        "original_record": row,
    }
    s3.put_object(
        Bucket=bucket, Key=sidecar_key,
        Body=json.dumps(sidecar, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )
    return sidecar_key


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    corr_id = getattr(context, "aws_request_id", "no-corr-id")
    chunk_key = event.get("chunk_key")
    file_key = event.get("file_key")
    file_sha256 = event.get("file_sha256")
    if not chunk_key or not file_key:
        raise ConfigError("Event missing required fields: chunk_key, file_key")

    bucket = _required_env("STAGING_BUCKET")
    learner = _required_env("LEARNER")
    table = _required_env("IDEMP_TABLE")

    LOG.info(json.dumps({
        "event": "validator_start", "corr_id": corr_id,
        "chunk_key": chunk_key, "file_key": file_key,
    }))

    obj = s3.get_object(Bucket=bucket, Key=chunk_key)
    lines = obj["Body"].read().decode("utf-8").splitlines()

    validated_rows: list[dict[str, Any]] = []
    counts = {"validated": 0, "quarantined": 0, "duplicate": 0}

    chunk_id = chunk_key.rsplit("/", 1)[-1].replace(".jsonl", "")

    for chunk_offset, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as e:
            # Use chunk_offset for malformed rows (we never parsed _line_no).
            _persist_quarantine(bucket, learner, "malformed", file_key,
                                chunk_offset, {"raw_line": raw_line}, str(e), corr_id)
            counts["quarantined"] += 1
            continue

        # Pull the global line number injected by the chunker; remove it from
        # the row so it doesn't leak into validated/ output.
        line_no = int(row.pop("_line_no", chunk_offset))

        # Row-level idempotency claim (first guard)
        row_pk = f"row#{file_key}:{line_no}"
        if not _claim_idempotency(table, row_pk, "claimed", ttl_days=30):
            counts["duplicate"] += 1
            continue

        # Schema validation
        try:
            _validate_schema(row, line_no, file_key)
        except SchemaError as e:
            _persist_quarantine(bucket, learner, "schema_drift", file_key,
                                line_no, row, str(e), corr_id)
            counts["quarantined"] += 1
            continue

        # Business-key idempotency claim (second guard)
        biz_pk = f"business#{_business_key(row)}"
        if not _claim_idempotency(table, biz_pk, "claimed", ttl_days=30):
            counts["duplicate"] += 1
            continue

        validated_rows.append(row)
        counts["validated"] += 1

    # Persist all surviving validated rows for this chunk
    if validated_rows:
        # All settlement_dates in this chunk should match; use first row's bsp_cycle
        settlement_date = validated_rows[0].get("bsp_cycle", "unknown")
        _persist_validated(bucket, learner, settlement_date, chunk_id, validated_rows)

    # Whole-chunk verdict: if >50% rows are quarantined, escalate
    total = counts["validated"] + counts["quarantined"]
    if total > 0 and (counts["quarantined"] / total) > 0.5:
        raise ValidationError(
            f"Chunk validation failure threshold breached: "
            f"{counts['quarantined']}/{total} rows quarantined",
            file_key=file_key,
            chunk_id=chunk_id,
            detail=json.dumps(counts),
        )

    LOG.info(json.dumps({
        "event": "validator_done", "corr_id": corr_id,
        "chunk_key": chunk_key, **counts,
    }))

    return {
        **counts,
        "chunk_key": chunk_key,
        "file_key": file_key,
        "file_sha256": file_sha256,
    }
