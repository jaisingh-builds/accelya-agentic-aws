"""
src/enricher/handler.py — Day 2 trainer showcase Lambda.

WHAT IT DOES
  Takes a single ticket-issue or cancellation record (or one S3 object containing them),
  asks Bedrock to classify the record into one of {refundable, partial_refund, no_refund,
  uncertain}, returns the enriched record with a `refund_classification` field.

WHY THIS LAMBDA EXISTS (in the programme)
  Day 2 introduces Lambda + IAM + S3 + CloudWatch — all "plumbing" services. This
  Lambda showcases what happens when you add Bedrock — the agentic intelligence layer
  the rest of the programme builds around.

  Side-by-side with src/validator/handler.py during the morning recap:
    - validator/handler.py  — pure rules engine; deterministic; fast (~250 ms); 256 MB.
    - enricher/handler.py   — LLM-backed; non-deterministic; slower (~2-5 s);  512 MB.

  Same input shape. Same output JSONL pattern. Same CloudWatch structured-log discipline.
  Different *kind* of work.

INVOKE
  - As S3 trigger:  drop a JSON file in s3://<bucket>/raw/trainer/.../
  - Manual:        aws lambda invoke --function-name accelya-m2-enricher-trainer ...

RUNTIME PROFILE
  - python3.12, arm64, 512 MB, 60s timeout
  - Env: BUCKET_NAME, BEDROCK_MODEL_ID, APP_VERSION
"""
import json
import os
import time
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "ap-south-1"))

BUCKET = os.environ["BUCKET_NAME"]
MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
)
APP_VERSION = os.environ.get("APP_VERSION", "m2-enricher")

# Cap how many records we send to Bedrock per invocation — sandbox is 50 inv / 20K tok / session.
# Each call here uses ~80-120 tokens; capping at 5 records keeps each invocation well under 1K tokens.
MAX_RECORDS_PER_INVOKE = int(os.environ.get("MAX_RECORDS_PER_INVOKE", "5"))


def emit(event_name, **fields):
    """JSON log line — same shape as the validator. Same CloudWatch Insights query plan."""
    print(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "INFO",
        "event": event_name,
        **fields,
    }))


def classify_with_bedrock(record, corr_id):
    """One synchronous Bedrock call per record. Returns the classification string."""
    prompt = (
        f"Classify this airline ticket cancellation into ONE of: "
        f"refundable, partial_refund, no_refund, uncertain.\n\n"
        f"Record: {json.dumps(record)}\n\n"
        f"Reply with ONE word only — no explanation."
    )

    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": "You are an airline settlement classifier. Reply with one word."}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 16, "temperature": 0.0},  # deterministic
    )

    classification = response["output"]["message"]["content"][0]["text"].strip().lower()
    usage = response["usage"]

    # Normalise — strip punctuation in case the model adds it
    classification = classification.replace(".", "").replace(",", "").split()[0]

    # Whitelist to the allowed labels
    allowed = {"refundable", "partial_refund", "no_refund", "uncertain"}
    if classification not in allowed:
        emit("classification_unexpected",
             corr_id=corr_id, raw=classification[:40])
        classification = "uncertain"

    return classification, usage["inputTokens"], usage["outputTokens"]


def lambda_handler(event, context):
    """
    Two invocation paths:
      - S3 PutObject event → read object, enrich each record (up to MAX), write enriched/<key>
      - Direct invoke with {"record": {...}} → enrich that one record, return inline
    """
    corr_id = context.aws_request_id
    start = time.time()

    # ── Path 1: direct invoke ─────────────────────────────────────────────
    if "record" in event:
        emit("received", corr_id=corr_id, function="enricher", path="direct-invoke")
        rec = event["record"]
        try:
            label, in_tok, out_tok = classify_with_bedrock(rec, corr_id)
            enriched = {**rec, "refund_classification": label}
            emit("classified",
                 corr_id=corr_id, function="enricher",
                 classification=label, input_tokens=in_tok, output_tokens=out_tok,
                 duration_ms=int((time.time() - start) * 1000),
                 version=APP_VERSION)
            return {"statusCode": 200, "enriched": enriched, "classification": label}
        except ClientError as e:
            emit("bedrock_error", corr_id=corr_id, error=str(e)[:200])
            return {"statusCode": 502, "error": str(e)[:200]}

    # ── Path 2: S3 trigger ─────────────────────────────────────────────────
    rec_meta = event["Records"][0]["s3"]
    key = unquote_plus(rec_meta["object"]["key"])
    emit("received",
         corr_id=corr_id, function="enricher", path="s3-trigger",
         key=key, zone="raw")

    # Fetch the source object
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    rows = json.loads(obj["Body"].read())

    # Cap how many we enrich (cost protection)
    sample = rows[:MAX_RECORDS_PER_INVOKE]
    skipped = len(rows) - len(sample)

    enriched = []
    total_in_tokens = 0
    total_out_tokens = 0
    classification_counts = {}

    for i, row in enumerate(sample):
        try:
            label, in_tok, out_tok = classify_with_bedrock(row, corr_id)
            enriched.append({**row, "refund_classification": label})
            total_in_tokens += in_tok
            total_out_tokens += out_tok
            classification_counts[label] = classification_counts.get(label, 0) + 1
        except ClientError as e:
            emit("bedrock_error_per_record",
                 corr_id=corr_id, record_index=i, error=str(e)[:200])
            enriched.append({**row, "refund_classification": "uncertain"})
            classification_counts["uncertain"] = classification_counts.get("uncertain", 0) + 1

    # Write enriched output to enriched/<learner>/...
    out_key = key.replace("raw/", "enriched/", 1)
    s3.put_object(
        Bucket=BUCKET,
        Key=out_key,
        Body=json.dumps(enriched).encode("utf-8"),
        ContentType="application/json",
    )

    emit("enriched",
         corr_id=corr_id, function="enricher",
         key=key, output_key=out_key, zone="raw",
         records_processed=len(sample),
         records_skipped_cost_cap=skipped,
         input_tokens_total=total_in_tokens,
         output_tokens_total=total_out_tokens,
         classification_counts=classification_counts,
         duration_ms=int((time.time() - start) * 1000),
         version=APP_VERSION)

    return {
        "statusCode": 200,
        "processed": len(sample),
        "skipped_cost_cap": skipped,
        "classification_counts": classification_counts,
    }
