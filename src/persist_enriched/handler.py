"""
src/persist_enriched/handler.py — Day 8 Lab 1 reference handler.

Persists enriched events to S3 under the enriched/ zone, partitioned by
ingest_date and source_system. Invoked as a Step Functions Task after
BedrockEnrich.

Input (from BedrockEnrich Task):
    Full envelope + enrichment fields (enrichment, sampled, enriched_at,
    budget_guard_skipped).

Output:
    { "persisted_key": "<s3 key>", "outcome": "persisted" }

S3 layout (one file per event):
    s3://<bucket>/enriched/<learner>/ingest_date=YYYY-MM-DD/source_system=GDS/events-<event_id>.jsonl.gz

Environment variables required:
    BUCKET_NAME    e.g. accelya-airline-data-ap-south-1
    LEARNER        learner suffix

Runtime: python3.12 · 512 MB · 30 s timeout · region ap-south-1.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.exceptions import ConfigError  # noqa: E402

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
s3 = boto3.client("s3", region_name=REGION)


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    corr_id = event.get("corr_id") or getattr(context, "aws_request_id", "no-corr-id")
    event_id = event.get("event_id", "unknown")

    bucket = _required_env("BUCKET_NAME")
    learner = _required_env("LEARNER")

    ingest_date = (event.get("ingest_time") or event.get("event_time") or
                   datetime.now(timezone.utc).isoformat())[:10]
    source_system = event.get("source_system", "UNKNOWN")

    key = (
        f"enriched/{learner}/"
        f"ingest_date={ingest_date}/"
        f"source_system={source_system}/"
        f"events-{event_id}.jsonl.gz"
    )

    # Add persistence metadata
    record = {
        **event,
        "consumer_seq":       event.get("stream_pk", "").split("#")[-1],
        "consumer_shard":     event.get("stream_pk", "").split("#")[-2]
                              if event.get("stream_pk", "").count("#") >= 3 else None,
        "sfn_execution_arn":  os.environ.get("AWS_EXECUTION_ENV", "unknown"),
        "persisted_at":       int(time.time()),
    }

    body = json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"
    gz_body = gzip.compress(body)

    s3.put_object(
        Bucket=bucket, Key=key, Body=gz_body,
        ContentType="application/gzip",
        ContentEncoding="gzip",
    )

    LOG.info(json.dumps({
        "event": "persisted", "corr_id": corr_id,
        "event_id": event_id, "key": key,
        "sampled": event.get("sampled"),
        "bytes": len(gz_body),
    }))

    return {"persisted_key": key, "outcome": "persisted"}
