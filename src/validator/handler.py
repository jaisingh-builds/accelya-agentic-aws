"""
src/validator/handler.py — Day 2 Lab 3 trainer-provided handler.

Lambda handler anatomy: ASL-driven validator for airline ticket-issue files.
Same shape every Lambda you write in this program.

Deploy via (Lab 3 step 2):
    cd src/validator && zip -j /tmp/validator.zip handler.py && cd -
    aws lambda update-function-code \\
      --function-name accelya-m2-validator-<your-name> \\
      --zip-file fileb:///tmp/validator.zip --region ap-south-1
    aws lambda wait function-updated-v2 --function-name accelya-m2-validator-<your-name>

Runtime: python3.12 (or 3.13) · 256 MB · 30s timeout

HITL dimension anchors:
  Correctness    — boto3.s3.put_object real APIs; REQUIRED set in code
  Security       — BUCKET_NAME via env; no hardcoded ARNs; IAM provides creds
  Observability  — context.aws_request_id propagated as corr_id in every log line
  Scalability    — Idempotent: replays produce same end-state (PUT is overwrite-safe)
  Cost           — Bounded: 256 MB · 30s · reads one object · writes at most two
"""
import json
import os
import time
from urllib.parse import unquote_plus

import boto3

s3 = boto3.client("s3")
BUCKET = os.environ["BUCKET_NAME"]

# Lowercase snake_case — same programme schema used in D4-D6.
REQUIRED = {"pnr", "airline_code", "fare_class", "od_pair", "settlement_date"}


def emit(event_name, **fields):
    """JSON log line for CloudWatch Insights. Every Lambda in this programme uses this shape."""
    print(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "INFO",
        "event": event_name,
        **fields,
    }))


def lambda_handler(event, context):
    """
    S3 PutObject in raw/<learner>/ triggers this handler.
    Splits incoming records into validated/ and quarantine/ subsets.
    """
    corr_id = context.aws_request_id
    start = time.time()

    # Lab simplification: one S3 record per upload (loop in production).
    rec = event["Records"][0]["s3"]
    key = unquote_plus(rec["object"]["key"])  # S3 keys are URL-encoded

    emit("received",
         corr_id=corr_id, function="validator", key=key, zone="raw")

    # Read the source object
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    rows = json.loads(obj["Body"].read())

    # Validate each row against REQUIRED schema fields
    bad = [r for r in rows if not REQUIRED.issubset(r)]
    good = [r for r in rows if REQUIRED.issubset(r)]
    airline_code = rows[0].get("airline_code", "UNKNOWN") if rows else "UNKNOWN"

    # Idempotent writes — same key replays produce same end-state.
    # `count=1` on replace() ensures we replace only the FIRST occurrence of "raw/" in the key.
    s3.put_object(
        Bucket=BUCKET,
        Key=key.replace("raw/", "validated/", 1),
        Body=json.dumps(good).encode("utf-8"),
        ContentType="application/json",
    )
    if bad:
        s3.put_object(
            Bucket=BUCKET,
            Key=key.replace("raw/", "quarantine/", 1),
            Body=json.dumps(bad).encode("utf-8"),
            ContentType="application/json",
        )

    emit("validated",
         corr_id=corr_id, function="validator",
         airline_code=airline_code, key=key, zone="raw",
         records_total=len(rows),
         records_good=len(good),
         records_bad=len(bad),
         duration_ms=int((time.time() - start) * 1000),
         version=os.getenv("APP_VERSION", "m2"))

    return {"statusCode": 200, "good": len(good), "bad": len(bad)}
