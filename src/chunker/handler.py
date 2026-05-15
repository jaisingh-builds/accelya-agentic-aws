"""
src/chunker/handler.py — Day 5 Lab 1 reference handler.

Stage 1 of the validator-pipeline state machine.

Invocation model:
    Step Functions Task -> Lambda (direct, NO SQS).
    Resource:   arn:aws:states:::lambda:invoke
    Payload.$:  "$"
    OutputPath: "$.Payload"

Event in (from ASL StartAt):
    { "file_key": "raw/synthetic/m4-failures/01-schema-drift.json" }

Return shape (becomes ASL state via OutputPath):
    {
      "file_key":     "<input file_key>",
      "file_sha256":  "<64-hex>",
      "row_count":    <int>,
      "chunk_keys":   ["staging/<learner>/<sha>/chunk-0001.jsonl", ...]
    }

Why we chunk:
    Step Functions execution state is capped at 256 KiB. We CANNOT pass
    `rows[]` through ASL state. We pass chunk_keys (S3 paths) instead.
    Each chunk holds CHUNK_SIZE rows on S3 staging.

Failure routes (ASL Catch in validator-pipeline.asl.json):
    MalformedRowError  -> QuarantineMalformed   (file not JSON / not parseable)
    ConfigError        -> NotifyOps             (env var missing)

Environment variables required:
    STAGING_BUCKET     S3 bucket for staging chunks (e.g. accelya-airline-data-ap-south-1)
    STAGING_PREFIX     S3 prefix root (default: "staging")
    LEARNER            learner name suffix
    CHUNK_SIZE         rows per chunk (default: 200)

Runtime: python3.12 · 1024 MB · 60 s timeout · runs in ap-south-1.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from typing import Any

import boto3

# common/ is a sibling package; relative import works once Lambda layer is built
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.exceptions import ConfigError, MalformedRowError  # noqa: E402

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-south-1"))


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def _parse_rows(raw_bytes: bytes, file_key: str) -> list[dict[str, Any]]:
    """Parse the raw file as JSON list-of-objects. Raise MalformedRowError on failure."""
    try:
        text = raw_bytes.decode("utf-8")
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise MalformedRowError(
            f"File not parseable as UTF-8 JSON: {e}",
            file_key=file_key,
            detail=str(e),
        ) from e
    if not isinstance(data, list):
        raise MalformedRowError(
            "Top-level JSON must be a list of objects",
            file_key=file_key,
            detail=f"got type={type(data).__name__}",
        )
    return data


def _write_chunk(bucket: str, key: str, rows: list[dict[str, Any]]) -> None:
    body = "\n".join(json.dumps(r, separators=(",", ":")) for r in rows).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/x-ndjson")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Chunker entry point."""
    corr_id = getattr(context, "aws_request_id", "no-corr-id")
    file_key = event.get("file_key")
    if not file_key:
        raise ConfigError("Event missing required field: file_key")

    bucket = _required_env("STAGING_BUCKET")
    learner = _required_env("LEARNER")
    prefix = os.environ.get("STAGING_PREFIX", "staging")
    chunk_size = int(os.environ.get("CHUNK_SIZE", "200"))

    LOG.info(json.dumps({
        "event": "chunker_start", "corr_id": corr_id,
        "file_key": file_key, "chunk_size": chunk_size,
    }))

    # Read raw file
    try:
        obj = s3.get_object(Bucket=bucket, Key=file_key)
        raw_bytes = obj["Body"].read()
    except s3.exceptions.NoSuchKey as e:
        raise MalformedRowError(
            f"Raw object missing: s3://{bucket}/{file_key}",
            file_key=file_key, detail=str(e),
        ) from e

    file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    rows = _parse_rows(raw_bytes, file_key)
    row_count = len(rows)

    # Write chunks to S3 staging.
    # Embed _line_no (1-indexed, global to the source file) into each row so the
    # validator's row# idempotency claim is unique across chunks.
    chunk_keys: list[str] = []
    for i in range(0, row_count, chunk_size):
        chunk_idx = (i // chunk_size) + 1
        chunk_key = f"{prefix}/{learner}/{file_sha256}/chunk-{chunk_idx:04d}.jsonl"
        annotated = [
            {**r, "_line_no": i + offset + 1}
            for offset, r in enumerate(rows[i : i + chunk_size])
        ]
        _write_chunk(bucket, chunk_key, annotated)
        chunk_keys.append(chunk_key)

    LOG.info(json.dumps({
        "event": "chunker_done", "corr_id": corr_id,
        "file_key": file_key, "file_sha256": file_sha256,
        "row_count": row_count, "chunk_count": len(chunk_keys),
    }))

    return {
        "file_key": file_key,
        "file_sha256": file_sha256,
        "row_count": row_count,
        "chunk_keys": chunk_keys,
    }
