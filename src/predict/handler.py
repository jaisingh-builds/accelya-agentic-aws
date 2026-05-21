"""
src/predict/handler.py — Day 9 Lab 2 reference handler.

Wrapper Lambda invoking the SageMaker Serverless endpoint
`accelya-cancel-risk-<learner>`. Invoked as the PredictCancelRisk branch
of the ASL Parallel state in `inference-pipeline-<learner>`.

Critical contract (from MODEL CONTEXT in .windsurfrules v6):

  - Confidence threshold is env-driven (CONFIDENCE_THRESHOLD, default '0.7')
  - low_confidence is a NORMAL OUTPUT FLAG, NOT an exception
  - Two custom exceptions ONLY: EndpointColdStartTimeout, EndpointThrottleException
  - NEVER raise LowConfidencePrediction
  - Timeout lockstep: ASL retry 10s < boto3 read_timeout 35s < Lambda timeout 45s
  - ContentType + Accept = 'application/json' BOTH required on invoke_endpoint

Event in (from ASL Parallel branch):
    Full envelope from consumer, including:
      { event_id, event_type, airline_code, booking_date, pnr,
        ...payload fields the model needs...
        booking_id, fare_amount, refund_lag_hours, prior_cancels,
        corr_id, stream_pk }

Return shape (ASL OutputPath: $.Payload):
    { risk_score:       0..1,
      confidence:       0..1,
      model_version:    str,
      low_confidence:   bool,    # NORMAL FLAG
      model_latency_ms: int,
      ...passthrough envelope fields }

Environment variables:
    ENDPOINT_NAME          e.g. accelya-cancel-risk-<learner>
    CONFIDENCE_THRESHOLD   default '0.7'

Runtime: python3.12 · x86_64 · 512 MB · 45 s timeout · region ap-south-1.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.exceptions import (  # noqa: E402
    ConfigError,
    EndpointColdStartTimeout,
    EndpointThrottleException,
    PipelineError,
)

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")

# boto3 client with strict timeouts — ASL owns retry (max_attempts=0 here)
sm_runtime = boto3.client(
    "sagemaker-runtime",
    region_name=REGION,
    config=Config(
        connect_timeout=5,
        read_timeout=35,
        retries={"max_attempts": 0},
    ),
)


def _required_env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        raise ConfigError(f"Required env var missing: {name}")
    return val


def _build_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Extract the 4 model-input features from the envelope.

    Supports two shapes:
      (a) flat in event (test invocation): event['booking_id'], event['fare_amount'], ...
      (b) nested in payload (real consumer flow):
          event['booking_id'] OR event.get('payload', {}).get('booking_id') etc.
    """
    src = event.get("payload", event)  # fall back to flat
    return {
        "booking_id":       str(src.get("booking_id", event.get("booking_id", "unknown"))),
        "fare_amount":      float(src.get("fare_amount", event.get("fare_amount", 0.0))),
        "refund_lag_hours": float(src.get("refund_lag_hours", event.get("refund_lag_hours", 0.0))),
        "prior_cancels":    int(src.get("prior_cancels", event.get("prior_cancels", 0))),
    }


def _emit_emf(metrics: dict[str, Any], endpoint_name: str, corr_id: str) -> None:
    """EMF metric log line — CloudWatch extracts metrics server-side."""
    print(json.dumps({
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "Accelya/Inference",
                "Dimensions": [["EndpointName", "Function"]],
                "Metrics": [
                    {"Name": "model_invoked",        "Unit": "Count"},
                    {"Name": "low_confidence",       "Unit": "Count"},
                    {"Name": "fallback_used",        "Unit": "Count"},
                    {"Name": "cold_start_timeout",   "Unit": "Count"},
                    {"Name": "throttle_exception",   "Unit": "Count"},
                    {"Name": "model_latency_ms",     "Unit": "Milliseconds"},
                    {"Name": "confidence",           "Unit": "None"},
                ],
            }],
        },
        "EndpointName":  endpoint_name,
        "Function":      "predict",
        "corr_id":       corr_id,
        **metrics,
    }))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    corr_id = event.get("corr_id") or getattr(context, "aws_request_id", "no-corr-id")
    event_id = event.get("event_id", "unknown")

    endpoint_name = _required_env("ENDPOINT_NAME")
    threshold = float(_required_env("CONFIDENCE_THRESHOLD", "0.7"))

    metrics: dict[str, Any] = {
        "model_invoked": 0,
        "low_confidence": 0,
        "fallback_used": 0,
        "cold_start_timeout": 0,
        "throttle_exception": 0,
        "model_latency_ms": 0,
        "confidence": 0.0,
    }

    LOG.info(json.dumps({
        "event": "predict_start", "corr_id": corr_id,
        "event_id": event_id, "endpoint": endpoint_name,
        "threshold": threshold,
    }))

    payload = _build_payload(event)
    body_bytes = json.dumps(payload).encode("utf-8")

    # Invoke the endpoint — track latency
    start_ts = time.time()
    try:
        resp = sm_runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="application/json",
            Accept="application/json",
            Body=body_bytes,
        )
    except (ReadTimeoutError, ConnectTimeoutError) as e:
        metrics["cold_start_timeout"] = 1
        _emit_emf(metrics, endpoint_name, corr_id)
        raise EndpointColdStartTimeout(
            f"socket timeout invoking {endpoint_name}: {e}",
            detail=str(e),
        ) from e
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")

        if code == "ServiceUnavailableException" or status == 503:
            metrics["throttle_exception"] = 1
            _emit_emf(metrics, endpoint_name, corr_id)
            raise EndpointThrottleException(
                f"throttled: {code} ({status})",
                detail=str(e),
            ) from e

        if code in ("ModelError", "InternalFailure") and status == 504:
            metrics["cold_start_timeout"] = 1
            _emit_emf(metrics, endpoint_name, corr_id)
            raise EndpointColdStartTimeout(
                f"cold-start 504: {code}",
                detail=str(e),
            ) from e

        # Other ModelError / non-retryable
        _emit_emf(metrics, endpoint_name, corr_id)
        err_msg = e.response.get("Error", {}).get("Message", "")
        raise PipelineError(
            f"invoke failed: {code} status={status} msg={err_msg!r}",
            detail=str(e),
        ) from e

    elapsed_ms = int((time.time() - start_ts) * 1000)
    metrics["model_latency_ms"] = elapsed_ms

    # Body parsing — 5-step checklist
    try:
        raw_bytes = resp["Body"].read()                           # 1. StreamingBody → bytes
        decoded = raw_bytes.decode("utf-8")                       # 2. utf-8 BEFORE json.loads
        body = json.loads(decoded)
        model_version = body.get("model_version")
        if not model_version:                                     # 3. Validate model_version
            raise PipelineError(
                "model response missing model_version",
                detail=decoded[:200],
            )
        risk_score = float(body.get("risk_score", 0.0))           # 4. Coerce numerics
        confidence = float(body.get("confidence", 0.0))
    except (KeyError, ValueError, json.JSONDecodeError) as e:     # 5. Wrap as PipelineError
        raise PipelineError(
            f"malformed model response: {e}",
            detail=str(e),
        ) from e

    # Confidence flag (NORMAL OUTPUT, not exception)
    low_confidence = confidence < threshold

    metrics["model_invoked"] = 1
    metrics["confidence"] = confidence
    if low_confidence:
        metrics["low_confidence"] = 1

    _emit_emf(metrics, endpoint_name, corr_id)

    LOG.info(json.dumps({
        "event": "predict_done", "corr_id": corr_id,
        "event_id": event_id,
        "risk_score": risk_score,
        "confidence": confidence,
        "low_confidence": low_confidence,
        "model_version": model_version,
        "model_latency_ms": elapsed_ms,
    }))

    # Return: pass through original event + add prediction fields
    return {
        **event,
        "risk_score":       risk_score,
        "confidence":       confidence,
        "model_version":    model_version,
        "low_confidence":   low_confidence,
        "model_latency_ms": elapsed_ms,
    }
