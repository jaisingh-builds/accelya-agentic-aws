"""
src/bedrock_enrich/handler.py — Day 8 Lab 1 reference handler.

Sampled Bedrock enrichment, invoked as a Step Functions Task.

Behavior per invocation:
    - should_enrich(event_id, SAMPLE_RATE): MD5 % SAMPLE_RATE == 0 → enrich
    - HARD COST GUARD: check cumulative Bedrock invocations + tokens
        if at cap → skip enrichment, persist enrichment=NULL,
                    emit budget_guard_skipped metric
    - On throttle: raise BedrockThrottleError (ASL retries with backoff)
    - Returns payload extended with: enrichment, sampled, enriched_at,
      consumer_seq, consumer_shard

Invoked by:
    Step Functions Task in inference-pipeline-<learner> state machine.
    State name: BedrockEnrich
    Retry: BedrockThrottleError → IntervalSeconds 2, MaxAttempts 3, BackoffRate 2.0
    Catch: States.ALL → Quarantine

Environment variables:
    SAMPLE_RATE                 (default 10) — 1-in-N sampling
    BEDROCK_MAX_INVOCATIONS     (default 38) — hard cost guard
    BEDROCK_MAX_TOKENS          (default 18000) — hard cost guard
    MODEL_ID                    (default APAC Sonnet profile)
    LEARNER                     learner suffix

Runtime: python3.12 · 1024 MB · 60 s timeout · region ap-south-1.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.exceptions import (  # noqa: E402
    BedrockThrottleError,
    ConfigError,
)

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
bedrock = boto3.client("bedrock-runtime", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)

DEFAULT_MODEL = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"


def _required_env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def _should_enrich(event_id: str, sample_rate: int) -> bool:
    """Deterministic 1-in-N sampling. Replay-safe (NOT random)."""
    if sample_rate <= 0:
        return True
    h = int(hashlib.md5(event_id.encode("utf-8")).hexdigest(), 16)
    return (h % sample_rate) == 0


def _check_budget_guard(max_invocations: int, max_tokens: int,
                        model_id: str) -> tuple[bool, dict[str, int]]:
    """Returns (allowed, current_usage). On error, allow (fail-open)."""
    try:
        end = datetime.now(timezone.utc)
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)

        def metric(name: str) -> float:
            resp = cloudwatch.get_metric_statistics(
                Namespace="AWS/Bedrock",
                MetricName=name,
                Dimensions=[{"Name": "ModelId", "Value": model_id}],
                StartTime=start, EndTime=end,
                Period=86400,
                Statistics=["Sum"],
            )
            dps = resp.get("Datapoints", [])
            return dps[0]["Sum"] if dps else 0.0

        cur_inv = int(metric("Invocations"))
        cur_tok = int(metric("InputTokenCount") + metric("OutputTokenCount"))
        allowed = cur_inv < max_invocations and cur_tok < max_tokens
        return allowed, {"invocations": cur_inv, "tokens": cur_tok}
    except ClientError as e:
        LOG.warning(json.dumps({
            "event": "budget_check_failed",
            "error": str(e), "fail_open": True,
        }))
        return True, {"invocations": -1, "tokens": -1}


def _invoke_bedrock(prompt: str, model_id: str) -> dict[str, Any]:
    """Call Bedrock; map common exceptions; return parsed body."""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 256,
        "messages": [{"role": "user", "content": prompt}],
    })
    try:
        resp = bedrock.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("ThrottlingException", "ServiceUnavailableException",
                    "TooManyRequestsException"):
            raise BedrockThrottleError(
                f"Bedrock throttled: {code}",
                detail=str(e),
            ) from e
        if code in ("AccessDeniedException", "ValidationException"):
            raise ConfigError(
                f"Bedrock access/validation error: {code}",
                detail=str(e),
            ) from e
        raise

    return json.loads(resp["body"].read())


def _build_prompt(event: dict[str, Any]) -> str:
    """Tight JSON-only prompt; ~150 input tokens / ~100 output tokens."""
    return (
        "You are a booking-event enrichment service. Return JSON only — "
        "no prose. Required fields: sentiment (positive|neutral|negative), "
        "priority (low|normal|high), summary (≤15 words).\n\n"
        f"Event: {json.dumps(event, separators=(',', ':'))}"
    )


def _emit_emf(metrics: dict[str, Any], model_id: str, corr_id: str) -> None:
    """One EMF log line per invocation."""
    print(json.dumps({
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "Accelya/Streaming",
                "Dimensions": [["ModelId", "Function"]],
                "Metrics": [
                    {"Name": "bedrock_invoked",       "Unit": "Count"},
                    {"Name": "bedrock_skipped",       "Unit": "Count"},
                    {"Name": "bedrock_throttled",     "Unit": "Count"},
                    {"Name": "budget_guard_skipped",  "Unit": "Count"},
                    {"Name": "input_tokens",          "Unit": "Count"},
                    {"Name": "output_tokens",         "Unit": "Count"},
                ],
            }],
        },
        "ModelId":   model_id,
        "Function":  "bedrock-enrich",
        "corr_id":   corr_id,
        **metrics,
    }))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions Task entry point.

    Input: full envelope from consumer (stream_pk, corr_id, plus original fields).
    Output: envelope + enrichment fields.
    """
    corr_id = event.get("corr_id") or getattr(context, "aws_request_id", "no-corr-id")
    event_id = event.get("event_id", "unknown")

    sample_rate = int(_required_env("SAMPLE_RATE", "10"))
    max_inv = int(_required_env("BEDROCK_MAX_INVOCATIONS", "38"))
    max_tok = int(_required_env("BEDROCK_MAX_TOKENS", "18000"))
    model_id = _required_env("MODEL_ID", DEFAULT_MODEL)

    metrics = {
        "bedrock_invoked": 0,
        "bedrock_skipped": 0,
        "bedrock_throttled": 0,
        "budget_guard_skipped": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }

    LOG.info(json.dumps({
        "event": "bedrock_enrich_start", "corr_id": corr_id,
        "event_id": event_id, "sample_rate": sample_rate,
    }))

    # Step 1: sampling decision
    if not _should_enrich(event_id, sample_rate):
        metrics["bedrock_skipped"] = 1
        _emit_emf(metrics, model_id, corr_id)
        return {**event,
                "enrichment": None,
                "sampled": False,
                "enriched_at": datetime.now(timezone.utc).isoformat()}

    # Step 2: hard cost guard
    allowed, usage = _check_budget_guard(max_inv, max_tok, model_id)
    if not allowed:
        LOG.warning(json.dumps({
            "event": "budget_guard_fired", "corr_id": corr_id,
            "usage": usage, "limits": {"invocations": max_inv, "tokens": max_tok},
        }))
        metrics["budget_guard_skipped"] = 1
        _emit_emf(metrics, model_id, corr_id)
        return {**event,
                "enrichment": None,
                "sampled": True,
                "budget_guard_skipped": True,
                "enriched_at": datetime.now(timezone.utc).isoformat()}

    # Step 3: Invoke Bedrock
    try:
        prompt = _build_prompt(event)
        resp = _invoke_bedrock(prompt, model_id)
    except BedrockThrottleError:
        metrics["bedrock_throttled"] = 1
        _emit_emf(metrics, model_id, corr_id)
        raise   # ASL Retry will handle
    except ConfigError:
        _emit_emf(metrics, model_id, corr_id)
        raise

    # Step 4: Parse + track tokens
    metrics["bedrock_invoked"] = 1
    usage_resp = resp.get("usage", {}) or {}
    metrics["input_tokens"] = int(usage_resp.get("input_tokens", 0))
    metrics["output_tokens"] = int(usage_resp.get("output_tokens", 0))

    enrichment_text = ""
    for block in resp.get("content", []):
        if block.get("type") == "text":
            enrichment_text += block.get("text", "")

    # Try to parse as JSON; if not, store raw text
    try:
        enrichment = json.loads(enrichment_text)
    except json.JSONDecodeError:
        enrichment = {"raw": enrichment_text.strip()}

    _emit_emf(metrics, model_id, corr_id)

    LOG.info(json.dumps({
        "event": "bedrock_enrich_done", "corr_id": corr_id,
        "event_id": event_id, "input_tokens": metrics["input_tokens"],
        "output_tokens": metrics["output_tokens"],
    }))

    return {**event,
            "enrichment": enrichment,
            "sampled": True,
            "budget_guard_skipped": False,
            "enriched_at": datetime.now(timezone.utc).isoformat()}
