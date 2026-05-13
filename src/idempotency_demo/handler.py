"""
src/idempotency_demo/handler.py — Day 4 OPTIONAL trainer demo Lambda.

WHAT IT DOES
  Demonstrates the 4 idempotency guards from Day 4 Concept 5, live.
  Receives a JSON payload representing a row + file context; tries to claim
  all 4 PK prefixes against the idempotency table; returns which were new
  (first-time-seen) and which were duplicates.

WHEN TO USE
  - Slide 17 live demo on Day 4 morning ("here's what the design looks like running").
  - Quick smoke test before Day 5 implementation labs.
  - Trainer-only — do NOT deploy a learner copy of this.

INVOKE
  aws lambda invoke --function-name accelya-m4-idempotency-demo-trainer \\
    --cli-binary-format raw-in-base64-out \\
    --payload file:///tmp/p.json \\
    --region ap-south-1 /tmp/out.json

PAYLOAD SHAPE
  {
    "file_key":         "raw/BSP/2026-05-08/m4-settlement-batch-001.json",
    "line_no":          42,
    "file_sha256":      "e3b0c44298fc1c149afbf4c8996fb924...",
    "canonical_hash":   "f7c3bc1d808e04732adf679965ccc34c...",
    "settlement_id":    "BSP-2026-W19-AI234-001"
  }

RUNTIME PROFILE
  python3.12, 256 MB, 30s, arm64. One DynamoDB table.
"""
import hashlib
import json
import os
import time

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["IDEMPOTENCY_TABLE"]   # e.g. idempotency_keys_trainer
REGION = os.environ.get("AWS_REGION", "ap-south-1")

# Module-level client — reused across warm invocations
ddb = boto3.client("dynamodb", region_name=REGION)


def emit(event_name, **fields):
    """JSON log line for CloudWatch Insights — same shape as other Lambdas in the programme."""
    print(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "INFO",
        "event": event_name,
        **fields,
    }))


def claim(pk: str, ttl_days: int) -> bool:
    """
    Atomic conditional-put. Returns True if we claimed (first time seen);
    False if this PK was already claimed (duplicate; skip silently).
    """
    now = int(time.time())
    ttl = now + (ttl_days * 86400)
    try:
        ddb.put_item(
            TableName=TABLE_NAME,
            Item={
                "pk":           {"S": pk},
                "processed_at": {"N": str(now)},
                "outcome":      {"S": "claimed"},
                "ttl":          {"N": str(ttl)},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True   # we own it
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False   # duplicate
        raise


def lambda_handler(event, context):
    """
    Tries all 4 guards in order. Returns per-guard verdict.
    Real validator Lambda (Day 5) would short-circuit on first duplicate;
    this demo runs all 4 so the cohort can see each guard's behaviour.
    """
    corr_id = context.aws_request_id
    start = time.time()

    file_key       = event.get("file_key", "demo/file.json")
    line_no        = event.get("line_no", 0)
    file_sha256    = event.get("file_sha256") or hashlib.sha256(file_key.encode()).hexdigest()
    canonical_hash = event.get("canonical_hash") or hashlib.sha256(f"canonical-{file_key}".encode()).hexdigest()
    settlement_id  = event.get("settlement_id", "BSP-2026-W19-DEMO-001")

    emit("received",
         corr_id=corr_id, function="idempotency_demo",
         file_key=file_key, line_no=line_no, settlement_id=settlement_id)

    # The 4 guards, each with its TTL per Concept 5
    guards = [
        ("row",       f"row#{file_key}:{line_no}",       30),
        ("file",      f"file#{file_sha256}",             90),
        ("canonical", f"canonical#{canonical_hash}",     90),
        ("business",  f"business#{settlement_id}",       30),
    ]

    results = {}
    for guard_name, pk, ttl_days in guards:
        is_new = claim(pk, ttl_days)
        results[guard_name] = {
            "pk":             pk,
            "ttl_days":       ttl_days,
            "first_time_seen": is_new,
            "verdict":        "claimed" if is_new else "duplicate",
        }
        emit("guard_checked",
             corr_id=corr_id, guard=guard_name, pk=pk,
             first_time_seen=is_new, verdict=results[guard_name]["verdict"])

    # If ALL 4 are new, this row is genuinely first-time. If ANY are duplicates,
    # real validator skips silently. Demo returns the full per-guard breakdown.
    all_new = all(r["first_time_seen"] for r in results.values())
    any_dup = any(not r["first_time_seen"] for r in results.values())

    emit("complete",
         corr_id=corr_id, function="idempotency_demo",
         all_new=all_new, any_duplicate=any_dup,
         duration_ms=int((time.time() - start) * 1000))

    return {
        "statusCode":         200,
        "all_first_time":     all_new,
        "any_duplicate":      any_dup,
        "guards":             results,
        "real_validator_would": "process" if all_new else "skip_silently",
    }
