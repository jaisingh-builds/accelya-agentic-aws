"""
src/dlq_replayer/handler.py — Day 5 Lab 3 reference handler.

REUSABLE DLQ replayer. Fully env-driven so the same Lambda binary serves
every DLQ in the programme (Lab 2 test-DLQ today; main pipeline DLQs in
Day 7+ streaming work).

Three classifiers off the `error_type` MessageAttribute:
    transient -> re-drive to MAIN_QUEUE_URL with incremented replay_attempt
    data      -> persist to quarantine/dlq_data/ + delete from DLQ
    config    -> publish to ESCALATION_TOPIC SNS + delete from DLQ

Hard cap: 100 messages per invocation. Bounded execution.

Invocation model:
    Step Functions Task (manually via aws stepfunctions start-execution today,
    EventBridge schedule rule every 15 min in production).

Event in:
    { "max_messages": 100 }

Return shape:
    { "transient_count": <int>,
      "data_count":      <int>,
      "config_count":    <int>,
      "processed_count": <int>,
      "remaining_estimate": <int> }

Environment variables required:
    DLQ_URL              URL of the DLQ to drain
    MAIN_QUEUE_URL       URL to re-drive transient messages to
    ESCALATION_TOPIC     SNS topic ARN for config-error escalation
    QUARANTINE_BUCKET    S3 bucket for data-error persistence
    LEARNER              learner name suffix

Runtime: python3.12 · 512 MB · 60 s timeout · region ap-south-1.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import boto3

# common/ is a sibling package; sys.path trick keeps the import working both
# (a) inside the Lambda zip (where common/ sits next to handler.py), and
# (b) in local dryrun where src/ is on sys.path.
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.exceptions import ConfigError  # noqa: E402

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
sqs = boto3.client("sqs", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)

MAX_REPLAY_ATTEMPTS = 3
HARD_CAP = 100

TRANSIENT_TYPES = {
    "TransientError", "ThrottledError", "ThrottlingException",
    "TimeoutError", "DependencyTimeoutError", "ServiceUnavailable",
}
DATA_TYPES = {
    "SchemaError", "ManifestMismatchError", "MalformedRowError",
    "ValidationError", "ReferenceError", "TypeMismatchError",
}


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def _classify(msg: dict[str, Any]) -> str:
    """Return one of: 'transient' | 'data' | 'config'.

    Classifies on `error_type` MessageAttribute (StringValue), NOT message body.
    The producer attached this attribute BEFORE the message was sent; SQS
    redrive preserved it through the DLQ landing.
    """
    attrs = msg.get("MessageAttributes", {}) or {}
    err = (attrs.get("error_type", {}) or {}).get("StringValue", "")
    if err in TRANSIENT_TYPES:
        return "transient"
    if err in DATA_TYPES:
        return "data"
    return "config"


def _replay_attempt(msg: dict[str, Any]) -> int:
    attrs = msg.get("MessageAttributes", {}) or {}
    raw = (attrs.get("replay_attempt", {}) or {}).get("StringValue", "0")
    try:
        return int(raw)
    except ValueError:
        return 0


def _redrive_transient(main_queue_url: str, msg: dict[str, Any],
                       new_attempt: int) -> None:
    attrs = dict(msg.get("MessageAttributes", {}) or {})
    attrs["replay_attempt"] = {"DataType": "String", "StringValue": str(new_attempt)}
    if "first_seen_at" not in attrs:
        attrs["first_seen_at"] = {
            "DataType": "String",
            "StringValue": str(int(time.time())),
        }
    sqs.send_message(
        QueueUrl=main_queue_url,
        MessageBody=msg["Body"],
        MessageAttributes={
            k: {"DataType": v["DataType"], "StringValue": v["StringValue"]}
            for k, v in attrs.items()
        },
    )


def _persist_data(bucket: str, learner: str, msg: dict[str, Any],
                  corr_id: str) -> None:
    msg_id = msg.get("MessageId", "unknown")
    key = f"quarantine/dlq_data/{learner}/{msg_id}.json"
    payload = {
        "reason": "dlq_data_error",
        "source_dlq": _required_env("DLQ_URL"),
        "correlation_id": corr_id,
        "moved_at": int(time.time()),
        "message_id": msg_id,
        "body": msg.get("Body"),
        "message_attributes": msg.get("MessageAttributes", {}),
    }
    s3.put_object(
        Bucket=bucket, Key=key,
        Body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )


def _escalate_config(topic: str, msg: dict[str, Any], reason: str,
                     corr_id: str) -> None:
    sns.publish(
        TopicArn=topic,
        Subject="DLQ replayer escalation",
        Message=json.dumps({
            "reason": reason,
            "correlation_id": corr_id,
            "message_id": msg.get("MessageId"),
            "body": msg.get("Body"),
            "message_attributes": msg.get("MessageAttributes", {}),
        }, separators=(",", ":")),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    corr_id = getattr(context, "aws_request_id", "no-corr-id")
    max_messages = min(int(event.get("max_messages", HARD_CAP)), HARD_CAP)

    dlq_url = _required_env("DLQ_URL")
    main_queue_url = _required_env("MAIN_QUEUE_URL")
    escalation_topic = _required_env("ESCALATION_TOPIC")
    quarantine_bucket = _required_env("QUARANTINE_BUCKET")
    learner = _required_env("LEARNER")

    LOG.info(json.dumps({
        "event": "replayer_start", "corr_id": corr_id,
        "max_messages": max_messages, "dlq_url": dlq_url,
    }))

    counts = {"transient_count": 0, "data_count": 0, "config_count": 0,
              "processed_count": 0}

    while counts["processed_count"] < max_messages:
        # SQS ReceiveMessage maxes at 10 per call
        batch_size = min(10, max_messages - counts["processed_count"])
        resp = sqs.receive_message(
            QueueUrl=dlq_url,
            MaxNumberOfMessages=batch_size,
            WaitTimeSeconds=2,
            MessageAttributeNames=["All"],
            AttributeNames=["All"],
        )
        msgs = resp.get("Messages", [])
        if not msgs:
            break

        for msg in msgs:
            classification = _classify(msg)
            attempt = _replay_attempt(msg)

            try:
                if classification == "transient":
                    if attempt >= MAX_REPLAY_ATTEMPTS:
                        # Replay cap exceeded -> escalate as if it were config
                        _escalate_config(
                            escalation_topic, msg,
                            "transient_replay_cap_exceeded", corr_id,
                        )
                        counts["config_count"] += 1
                    else:
                        _redrive_transient(main_queue_url, msg, attempt + 1)
                        counts["transient_count"] += 1
                elif classification == "data":
                    _persist_data(quarantine_bucket, learner, msg, corr_id)
                    counts["data_count"] += 1
                else:  # config
                    _escalate_config(escalation_topic, msg, "config_error", corr_id)
                    counts["config_count"] += 1

                # Delete from DLQ only after successful action
                sqs.delete_message(
                    QueueUrl=dlq_url,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
                counts["processed_count"] += 1

                LOG.info(json.dumps({
                    "event": "replayer_message", "corr_id": corr_id,
                    "message_id": msg.get("MessageId"),
                    "classification": classification, "attempt": attempt,
                }))
            except Exception as e:  # noqa: BLE001  intentional broad catch
                LOG.warning(json.dumps({
                    "event": "replayer_action_failed", "corr_id": corr_id,
                    "message_id": msg.get("MessageId"),
                    "classification": classification,
                    "error": type(e).__name__, "detail": str(e),
                }))
                # Leave the message in flight; visibility will return it

    # Approximate remaining (best-effort, not blocking)
    try:
        attrs = sqs.get_queue_attributes(
            QueueUrl=dlq_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )["Attributes"]
        remaining = int(attrs.get("ApproximateNumberOfMessages", 0))
    except Exception:  # noqa: BLE001
        remaining = -1

    LOG.info(json.dumps({
        "event": "replayer_done", "corr_id": corr_id,
        **counts, "remaining_estimate": remaining,
    }))

    return {**counts, "remaining_estimate": remaining}
