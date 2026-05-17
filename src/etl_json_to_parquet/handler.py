"""
src/etl_json_to_parquet/handler.py — Day 6 Lab 2 reference handler.

Converts one Day-5 validated JSONL chunk to a Parquet file in the curated
zone, partitioned by `ingest_date` and `source_system`.

Invocation model:
    Manual invoke today (aws lambda invoke).
    Day 11 wires this as a 4th Task into validator-pipeline.asl.json.

Event in:
    { "file_key":      "validated/<learner>/validated_settlement_json/source_system=BSP/ingest_date=2026-05-09/chunk-0001.jsonl",
      "source_system": "BSP",
      "ingest_date":   "2026-05-09",
      "chunk_id":      "0001" }

Return shape:
    { "status":          "converted" | "skipped" | "failed",
      "rows_in":         <int>,
      "rows_out":        <int>,
      "parquet_key":     "curated/settlement/ingest_date=2026-05-09/source_system=BSP/part-00001.parquet",
      "file_sha256_in":  "...",
      "file_sha256_out": "..." }

Failure routes:
    SchemaInferenceError  — input has columns that don't fit fixed SCHEMA
    ConfigError           — env var missing

Environment variables required:
    BUCKET_NAME    S3 bucket (e.g. accelya-airline-data-ap-south-1)
    LEARNER        learner name suffix

Runtime: python3.12 · x86_64 · 1024 MB · 180 s timeout · region ap-south-1.
Layer:   AWSSDKPandas-Python312 (PyArrow + pandas + boto3-stubs)
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import boto3

# Imports for PyArrow are deferred to handler() so the module parses locally
# (where the AWSSDKPandas layer isn't installed) without raising.

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.exceptions import ConfigError, SchemaInferenceError  # noqa: E402

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
s3 = boto3.client("s3", region_name=REGION)


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def _build_schema():
    """Return the fixed Parquet schema (v3) — call inside handler so PyArrow
    import is lazy."""
    import pyarrow as pa
    return pa.schema([
        pa.field("settlement_id", pa.string()),
        pa.field("airline_code", pa.string()),
        pa.field("pnr", pa.string()),
        pa.field("fare_class", pa.string()),
        pa.field("od_pair", pa.string()),
        pa.field("ticket_number", pa.string()),
        pa.field("bsp_cycle", pa.string()),
        pa.field("issue_date", pa.timestamp("ms")),
        pa.field("fare_amount", pa.decimal128(12, 2)),
        pa.field("currency", pa.string()),
        pa.field("commission_pct", pa.decimal128(5, 4)),
        pa.field("refund_status", pa.string()),
        pa.field("agency_iata", pa.string()),
    ])


def _normalise_inbound(rec: dict[str, Any]) -> dict[str, Any]:
    """Map known inbound variations onto the canonical schema.

    Currently handles:
      - `amount` -> `fare_amount`  (some upstream sources rename this field)
      - `fare_amount` as STRING ('2845.0') -> coerced to float by table.cast
      - `issue_date` ISO-8601 with timezone offset -> normalise to UTC-naive
        datetime that PyArrow timestamp('ms') accepts. BSP feed timestamps
        carry +05:30 offsets; we store as UTC for cross-source comparability.
    """
    if "amount" in rec and "fare_amount" not in rec:
        rec["fare_amount"] = rec.pop("amount")
    # Strip any chunker-injected internal fields
    rec.pop("_line_no", None)
    # Normalise issue_date: ISO-8601 string with offset -> UTC-naive datetime
    iso = rec.get("issue_date")
    if isinstance(iso, str):
        try:
            # datetime.fromisoformat handles "2026-05-08T11:42:00+05:30"
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            rec["issue_date"] = dt
        except ValueError:
            # leave it for the cast to surface a clear error
            pass
    return rec


def _make_curated_key(learner: str, ingest_date: str,
                      source_system: str, chunk_id: str) -> str:
    return (
        f"curated/settlement/"
        f"ingest_date={ingest_date}/"
        f"source_system={source_system}/"
        f"part-{chunk_id}.parquet"
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    corr_id = getattr(context, "aws_request_id", "no-corr-id")
    file_key = event.get("file_key")
    source_system = event.get("source_system")
    ingest_date = event.get("ingest_date")
    chunk_id = event.get("chunk_id", "00000")

    if not (file_key and source_system and ingest_date):
        raise ConfigError(
            "Event missing required fields: file_key, source_system, ingest_date"
        )

    bucket = _required_env("BUCKET_NAME")
    learner = _required_env("LEARNER")

    LOG.info(json.dumps({
        "event": "etl_start", "corr_id": corr_id,
        "file_key": file_key, "source_system": source_system,
        "ingest_date": ingest_date,
    }))

    # Defer heavy imports until invocation
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = _build_schema()

    # Read JSONL from S3
    obj = s3.get_object(Bucket=bucket, Key=file_key)
    raw = obj["Body"].read()
    file_sha256_in = hashlib.sha256(raw).hexdigest()

    lines = raw.decode("utf-8").splitlines()
    records: list[dict[str, Any]] = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue  # Day-5 already quarantined malformed rows; defensive skip
        records.append(_normalise_inbound(rec))

    if not records:
        LOG.info(json.dumps({
            "event": "etl_empty", "corr_id": corr_id, "file_key": file_key,
        }))
        return {
            "status": "skipped", "rows_in": 0, "rows_out": 0,
            "parquet_key": None,
            "file_sha256_in": file_sha256_in,
            "file_sha256_out": None,
        }

    # Build the Arrow table; reorder columns to match target schema (cast() is
    # order-sensitive in newer PyArrow). Extra columns are silently dropped
    # (Lab 3 documents the additive-evolution fix). Missing columns become NULL
    # via the via-pylist construction with a default None.
    try:
        # Ensure every record has every schema field (None for missing)
        records_aligned = [
            {name: r.get(name) for name in schema.names}
            for r in records
        ]
        table = pa.Table.from_pylist(records_aligned)
        # Reorder columns to match schema (defensive — Python dict order
        # preservation should already handle this, but Table.from_pylist's
        # internal type inference can re-sort in some PyArrow versions).
        table = table.select(schema.names)
        table = table.cast(schema, safe=False)
    except (pa.lib.ArrowInvalid, pa.lib.ArrowTypeError, KeyError, ValueError) as e:
        raise SchemaInferenceError(
            f"Cannot cast inbound records to fixed schema: {e}",
            file_key=file_key,
            detail=str(e),
        ) from e

    # Write to in-memory buffer; upload to S3 as one Parquet file.
    buf = io.BytesIO()
    pq.write_table(
        table, buf,
        compression="snappy",
        write_statistics=True,
    )
    body = buf.getvalue()
    file_sha256_out = hashlib.sha256(body).hexdigest()

    parquet_key = _make_curated_key(learner, ingest_date, source_system, chunk_id)
    s3.put_object(
        Bucket=bucket, Key=parquet_key,
        Body=body, ContentType="application/octet-stream",
    )

    LOG.info(json.dumps({
        "event": "etl_done", "corr_id": corr_id,
        "parquet_key": parquet_key,
        "rows_in": len(records), "rows_out": table.num_rows,
        "bytes_out": len(body),
    }))

    return {
        "status": "converted",
        "rows_in": len(records),
        "rows_out": table.num_rows,
        "parquet_key": parquet_key,
        "file_sha256_in": file_sha256_in,
        "file_sha256_out": file_sha256_out,
    }
