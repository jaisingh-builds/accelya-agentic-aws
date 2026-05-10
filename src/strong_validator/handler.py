"""
strong_validator/handler.py — Cascade output against prompts/v2_validator.txt.

Trainer reference. Scores ~14/15 on the 5-dim HITL checklist:
  Correctness 3 · Security 3 · Observability 3 · Scalability 3 · Cost 2 = 14/15.
Cost is 2 (not 3) because v2 prompt didn't require Bedrock-invocation sampling
discipline yet — that anchor lands in Module 10.

Compare to src/weak_validator/handler.py (~5/15).
"""
import json
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

# REVIEW NOTES: Observability — module-level Logger + Metrics; correlation_id propagated below.
logger = Logger(service="strong-validator")
metrics = Metrics(namespace="Accelya/Validator", service="strong-validator")

# REVIEW NOTES: Scalability — clients created ONCE per cold start, reused across invocations.
s3 = boto3.client("s3")
ddb = boto3.client("dynamodb")

# REVIEW NOTES: Correctness — programme schema constants. Lowercase snake_case (no order_id, no user_email).
REQUIRED_FIELDS = {
    "pnr", "airline_code", "fare_class", "od_pair",
    "settlement_date", "ticket_number", "issue_date",
    "fare_amount", "currency", "agency_iata", "source_system",
}
IATA_AIRLINES = {"AI", "BA", "EK", "QR", "SQ", "TG", "MH", "EY", "GF", "WY"}  # subset; full list trainer-provided

BUCKET = os.environ["BUCKET"]                       # REVIEW NOTES: Security — env var, not hardcoded
IDEMPOTENCY_TABLE = os.environ["IDEMPOTENCY_TABLE"]
LEARNER = os.environ["LEARNER"]


# REVIEW NOTES: Observability — typed exceptions classified by category. NEVER bare except.
class SchemaError(Exception):
    quarantine_reason = "schema_drift"


class ReferenceError(Exception):  # noqa: A001 — shadows builtin intentionally
    quarantine_reason = "reference_drift"


class BusinessRuleError(Exception):
    quarantine_reason = "business_rule"


@logger.inject_lambda_context(correlation_id_path="awsRequestId")
@metrics.log_metrics
def lambda_handler(event: dict, context: Any) -> dict:
    """Validate ticket-issue records from S3. One file per invocation; line-by-line streaming."""

    correlation_id = context.aws_request_id
    counts = {"total": 0, "validated": 0, "quarantined": 0, "duplicate": 0}

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        logger.info("received", extra={"function": "validator", "key": key, "zone": "raw"})

        # REVIEW NOTES: Scalability — streaming line-by-line via S3 get_object iter_lines.
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            for line_no, raw_line in enumerate(obj["Body"].iter_lines(), start=1):
                counts["total"] += 1
                if not raw_line.strip():
                    continue
                try:
                    row = json.loads(raw_line)
                except json.JSONDecodeError as e:
                    _quarantine_row(
                        row={"raw": raw_line.decode("utf-8", errors="replace")},
                        reason="malformed",
                        key=key,
                        line_no=line_no,
                        correlation_id=correlation_id,
                        detail=str(e),
                    )
                    counts["quarantined"] += 1
                    continue

                outcome = _process_row(
                    row=row,
                    key=key,
                    line_no=line_no,
                    correlation_id=correlation_id,
                )
                counts[outcome] += 1

        except ClientError as e:
            # REVIEW NOTES: Observability — typed catch; logged and re-raised (no silent swallow).
            logger.error(
                "s3_get_object_failed",
                extra={"key": key, "error_code": e.response.get("Error", {}).get("Code")},
            )
            raise

    _emit_metrics(counts)
    return {"statusCode": 200, **counts}


def _process_row(row: dict, key: str, line_no: int, correlation_id: str) -> str:
    """Validate one row. Returns one of: validated, quarantined, duplicate."""

    # REVIEW NOTES: Scalability — idempotency claim BEFORE persist; replays are safe.
    pk = f"row#{key}:{line_no}"
    if _is_duplicate(pk, ttl_days=30):
        logger.info("duplicate_skipped", extra={"pk": pk, "line_no": line_no})
        return "duplicate"

    try:
        _validate_row(row)
    except SchemaError as e:
        _quarantine_row(row, "schema_drift", key, line_no, correlation_id, str(e))
        return "quarantined"
    except ReferenceError as e:
        _quarantine_row(row, "reference_drift", key, line_no, correlation_id, str(e))
        return "quarantined"
    except BusinessRuleError as e:
        _quarantine_row(row, "business_rule", key, line_no, correlation_id, str(e))
        return "quarantined"

    _persist_validated(row, key, line_no)
    return "validated"


def _validate_row(row: dict) -> None:
    """Schema + reference + business-rule checks. Raises typed exceptions on failure."""

    # REVIEW NOTES: Correctness — programme schema, lowercase snake_case, all required.
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        raise SchemaError(f"missing required fields: {sorted(missing)}")

    if row["airline_code"] not in IATA_AIRLINES:
        raise ReferenceError(f"airline_code '{row['airline_code']}' not in IATA list")

    if not isinstance(row.get("fare_class"), str) or len(row["fare_class"]) != 1:
        raise SchemaError("fare_class must be single character")

    if not isinstance(row.get("fare_amount"), (int, float)):
        raise SchemaError("fare_amount must be numeric")

    # REVIEW NOTES: Correctness — business rule: settlement_date not future-dated.
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if row["settlement_date"] > today:
        raise BusinessRuleError(f"settlement_date '{row['settlement_date']}' is future-dated")


def _is_duplicate(pk: str, ttl_days: int) -> bool:
    """Conditional PUT into idempotency_keys_<learner>. Returns True if already claimed."""

    ttl = int(time.time()) + (ttl_days * 86400)
    try:
        ddb.put_item(
            TableName=IDEMPOTENCY_TABLE,
            Item={"pk": {"S": pk}, "ttl": {"N": str(ttl)}},
            ConditionExpression="attribute_not_exists(pk)",
        )
        return False
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        # REVIEW NOTES: Observability — other errors logged + re-raised, not swallowed.
        logger.error("idempotency_check_failed", extra={"pk": pk, "error": str(e)})
        raise


def _persist_validated(row: dict, key: str, line_no: int) -> None:
    """Append one validated row to validated/<learner>/<basename>.jsonl"""

    basename = os.path.basename(key).replace(".json", "").replace(".csv", "")
    out_key = f"validated/{LEARNER}/{basename}.jsonl"
    # REVIEW NOTES: Scalability — line-append by streaming-write. For lab simplicity we
    # write one object per S3 PutObject; production would use multipart or batched flush.
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{out_key}.{line_no:06d}",
        Body=(json.dumps(row) + "\n").encode("utf-8"),
        ContentType="application/json",
    )


def _quarantine_row(
    row: dict, reason: str, key: str, line_no: int,
    correlation_id: str, detail: str = "",
) -> None:
    """Persist a quarantined row + sidecar JSON BEFORE any exception propagates."""

    out_prefix = f"quarantine/{reason}/{LEARNER}/{os.path.basename(key)}"
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{out_prefix}.{line_no:06d}.json",
        Body=json.dumps(row).encode("utf-8"),
        ContentType="application/json",
    )
    sidecar = {
        "reason": reason,
        "source_path": key,
        "line_no": line_no,
        "correlation_id": correlation_id,
        "trace_id": correlation_id,
        "detail": detail,
        "original_record": row,
    }
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{out_prefix}.{line_no:06d}.sidecar.json",
        Body=json.dumps(sidecar).encode("utf-8"),
        ContentType="application/json",
    )
    # REVIEW NOTES: Observability — structured log line per quarantine, with correlation_id.
    logger.warning(
        "quarantined",
        extra={
            "function": "validator", "reason": reason, "key": key,
            "line_no": line_no, "detail": detail,
        },
    )


def _emit_metrics(counts: dict) -> None:
    """Emit one EMF metric line per file, namespace Accelya/Validator."""
    # REVIEW NOTES: Observability — EMF metrics for downstream alarms in Module 10.
    metrics.add_metric(name="records_total", unit=MetricUnit.Count, value=counts["total"])
    metrics.add_metric(name="records_validated", unit=MetricUnit.Count, value=counts["validated"])
    metrics.add_metric(name="records_quarantined", unit=MetricUnit.Count, value=counts["quarantined"])
    metrics.add_metric(name="records_duplicate", unit=MetricUnit.Count, value=counts["duplicate"])
