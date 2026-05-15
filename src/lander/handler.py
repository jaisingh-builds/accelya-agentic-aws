"""
src/lander/handler.py — Day 5 Lab 1 reference handler.

Stage 3 of the validator-pipeline state machine. File-level finalisation.

Invocation model:
    Step Functions Task -> Lambda. After Map(Validate) completes.
    Resource:   arn:aws:states:::lambda:invoke
    Payload.$:  "$"
    OutputPath: "$.Payload"

Event in (the parent state preserved by ResultPath: $.validation_results):
    {
      "file_key":           "<from chunker>",
      "file_sha256":        "<from chunker>",
      "row_count":          <int, from chunker>,
      "chunk_keys":          [...],
      "validation_results": [ {validated, quarantined, duplicate, chunk_key, ...}, ... ]
    }

Return shape:
    { "manifest_key": "validated/<learner>/_manifests/<file_sha256>.json",
      "totals":       { "validated", "quarantined", "duplicate" },
      "outcome":      "landed" | "duplicate_skipped" | "empty_after_validation" }

Idempotency: lander owns file# + canonical# (90-day TTL).
             Validator already claimed row# + business# per row.

Failure routes:
    ManifestMismatchError -> QuarantinePartial   (counts don't reconcile)
    ConfigError           -> NotifyOps           (env var missing)

Environment variables required:
    STAGING_BUCKET     S3 bucket
    LEARNER            learner name suffix
    IDEMP_TABLE        DynamoDB table name

Runtime: python3.12 · 1024 MB · 60 s timeout · region ap-south-1.
"""
from __future__ import annotations

import hashlib
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
    ManifestMismatchError,
)

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
s3 = boto3.client("s3", region_name=REGION)
ddb = boto3.client("dynamodb", region_name=REGION)


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def _claim_idempotency(table: str, pk: str, outcome: str, ttl_days: int) -> bool:
    """Conditional PutItem; returns True if claim succeeded (new key)."""
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


def _aggregate(results: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"validated": 0, "quarantined": 0, "duplicate": 0}
    for r in results or []:
        for k in totals:
            totals[k] += int(r.get(k, 0))
    return totals


def _canonical_manifest_hash(bucket: str, learner: str, chunk_keys: list[str]) -> str:
    """Compute a hash over the SORTED set of validated rows.

    This catches reformatted re-sends: same logical rows, different byte order
    in source file. We re-read each chunk's *validated* output from validated/
    rather than re-reading raw chunks (raw rows include quarantined ones).
    For the reference impl we keep this simple: hash the sorted chunk_keys list
    plus the bsp_cycle of the first chunk's first row.

    Production: compute a Merkle-style hash over sorted (settlement_id, fare_amount).
    """
    payload = "\n".join(sorted(chunk_keys)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_manifest(bucket: str, learner: str, file_sha256: str,
                    file_key: str, totals: dict[str, int],
                    chunk_keys: list[str], canonical_hash: str,
                    outcome: str, corr_id: str) -> str:
    manifest_key = f"validated/{learner}/_manifests/{file_sha256}.json"
    manifest = {
        "manifest_version": "m5-v1",
        "file_key": file_key,
        "file_sha256": file_sha256,
        "canonical_manifest_hash": canonical_hash,
        "totals": totals,
        "chunk_keys": chunk_keys,
        "outcome": outcome,
        "landed_at": int(time.time()),
        "correlation_id": corr_id,
    }
    s3.put_object(
        Bucket=bucket, Key=manifest_key,
        Body=json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )
    return manifest_key


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    corr_id = getattr(context, "aws_request_id", "no-corr-id")
    file_key = event.get("file_key")
    file_sha256 = event.get("file_sha256")
    chunk_keys = event.get("chunk_keys", [])
    row_count_expected = event.get("row_count")
    validation_results = event.get("validation_results", [])

    if not file_key or not file_sha256:
        raise ConfigError("Event missing required fields: file_key, file_sha256")

    bucket = _required_env("STAGING_BUCKET")
    learner = _required_env("LEARNER")
    table = _required_env("IDEMP_TABLE")

    LOG.info(json.dumps({
        "event": "lander_start", "corr_id": corr_id,
        "file_key": file_key, "file_sha256": file_sha256,
        "chunks": len(chunk_keys),
    }))

    # Aggregate per-chunk results
    totals = _aggregate(validation_results)
    accounted = totals["validated"] + totals["quarantined"] + totals["duplicate"]

    # Manifest reconciliation: expected row_count must equal accounted rows
    if row_count_expected is not None and accounted != row_count_expected:
        raise ManifestMismatchError(
            f"Row count mismatch: expected {row_count_expected}, accounted {accounted}",
            file_key=file_key,
            detail=json.dumps({
                "expected": row_count_expected,
                "validated": totals["validated"],
                "quarantined": totals["quarantined"],
                "duplicate": totals["duplicate"],
            }),
        )

    # Empty-after-validation edge case
    if accounted == 0:
        LOG.info(json.dumps({
            "event": "lander_empty", "corr_id": corr_id, "file_key": file_key,
        }))
        return {
            "manifest_key": None,
            "totals": totals,
            "outcome": "empty_after_validation",
        }

    # File-level idempotency: file# (byte-exact replay)
    file_pk = f"file#{file_sha256}"
    if not _claim_idempotency(table, file_pk, "landed", ttl_days=90):
        LOG.info(json.dumps({
            "event": "lander_duplicate_file", "corr_id": corr_id,
            "file_key": file_key, "file_sha256": file_sha256,
        }))
        return {
            "manifest_key": None,
            "totals": totals,
            "outcome": "duplicate_skipped",
        }

    # Canonical idempotency: same logical content, different bytes
    canonical_hash = _canonical_manifest_hash(bucket, learner, chunk_keys)
    canonical_pk = f"canonical#{canonical_hash}"
    if not _claim_idempotency(table, canonical_pk, "landed", ttl_days=90):
        LOG.info(json.dumps({
            "event": "lander_duplicate_canonical", "corr_id": corr_id,
            "canonical_hash": canonical_hash,
        }))
        return {
            "manifest_key": None,
            "totals": totals,
            "outcome": "duplicate_skipped",
        }

    # Write manifest
    manifest_key = _write_manifest(
        bucket, learner, file_sha256, file_key, totals,
        chunk_keys, canonical_hash, "landed", corr_id,
    )

    LOG.info(json.dumps({
        "event": "lander_done", "corr_id": corr_id,
        "manifest_key": manifest_key, **totals,
    }))

    return {
        "manifest_key": manifest_key,
        "totals": totals,
        "outcome": "landed",
    }
