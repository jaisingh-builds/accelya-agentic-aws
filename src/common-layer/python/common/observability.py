"""
src/common/observability.py — programme observability helpers (Day 10).

This module is imported by every Lambda from Day 10 forward. It centralises:
- Structured JSON logger (powertools.Logger)
- EMF metrics emitter (powertools.Metrics)
- X-Ray tracer (powertools.Tracer)
- Correlation ID fallback chain
- Flush-early helper (call before timeout-risk operations)

Why a shared module:
- Without it, every Lambda hand-rolls 30-50 lines of boilerplate.
- 10 Lambdas × 50 lines = 500 lines of drift-prone duplication.
- One helper module = one place to fix bugs / upgrade powertools.

Pin: aws-lambda-powertools[tracer]==2.43.1 (declared in each Lambda's
requirements.txt and tested against this module). Upgrade requires the
trainer to re-validate the EMF schema (CW changes can be silent).
"""
from __future__ import annotations

import os
import uuid
from typing import Any

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit  # re-exported for callers


__all__ = [
    "get_logger",
    "get_metrics",
    "get_tracer",
    "get_correlation_id",
    "flush_metrics_early",
    "MetricUnit",        # convenience re-export so handlers import from one place
    "NAMESPACE",
]


# Single namespace for the whole programme (every EMF metric lives here).
NAMESPACE = "Accelya/Pipeline"


# ──────────────────────────────────────────────────────────────────────────
# Factory functions
#
# Each Lambda calls these ONCE at module load (not per-handler-call).
# powertools caches the underlying singletons; calling here is cheap.
# ──────────────────────────────────────────────────────────────────────────
def get_logger(service: str) -> Logger:
    """
    Return a powertools Logger pinned to this Lambda's service name.

    Usage in each handler.py:
        logger = get_logger(service='bedrock-enrich')

        @logger.inject_lambda_context(correlation_id_path='correlation_id',
                                      log_event=False)
        def handler(event, context): ...

    Notes:
    - log_event=False to avoid leaking PII (PNR, fare_amount) into logs.
      If you need to log the inbound event, add explicit fields:
          logger.info('processing', extra={'event_id': event['event_id']})
    - correlation_id_path='correlation_id' means powertools looks for
      event['correlation_id'] and auto-attaches it to all subsequent
      log lines. If the path is missing, no correlation_id is attached
      (we then call set_correlation_id() explicitly via get_correlation_id).
    """
    return Logger(service=service, sampling_rate=0)


def get_metrics(service: str) -> Metrics:
    """
    Return a powertools Metrics emitter pinned to NAMESPACE + service.

    Usage in each handler.py:
        metrics = get_metrics(service='bedrock-enrich')

        @metrics.log_metrics(capture_cold_start_metric=True)
        def handler(event, context):
            metrics.add_metric(name='RecordsOk', unit=MetricUnit.Count, value=1)

    The 'service' dimension is auto-attached to every metric emitted by
    this instance. Add at most 2 additional dimensions via add_dimension.

    capture_cold_start_metric=True emits a ColdStart=1|0 metric per
    invocation — useful for cold-start frequency dashboards.
    """
    return Metrics(namespace=NAMESPACE, service=service)


def get_tracer(service: str) -> Tracer:
    """
    Return a powertools Tracer pinned to this Lambda's service name.

    Usage in each handler.py:
        tracer = get_tracer(service='bedrock-enrich')

        @tracer.capture_lambda_handler
        def handler(event, context):
            with tracer.provider.in_subsegment('preprocess'):
                ...

    Auto-instruments boto3 (Bedrock, SageMaker, DynamoDB, S3, etc.) when
    TracingConfig=Active is set on the Lambda. Each boto3 call becomes
    a subsegment of the Lambda's segment in X-Ray.

    Disabled when env LAMBDA_TASK_ROOT is unset (i.e. local pytest) —
    powertools handles that automatically.
    """
    return Tracer(service=service)


# ──────────────────────────────────────────────────────────────────────────
# Correlation ID resolution
# ──────────────────────────────────────────────────────────────────────────
def get_correlation_id(event_envelope: dict[str, Any] | None) -> str:
    """
    Resolve the correlation_id for this invocation, using a 4-step fallback.

    Why a fallback chain:
    - Not every Lambda receives a uniform envelope shape.
    - validator Lambda gets raw S3 records (no correlation_id field).
    - consumer Lambda gets Kinesis Records[] (envelope is inside record.data).
    - persist_enriched gets the SFN execution output (correlation_id at top).
    - bedrock_enrich + predict get the inner record (correlation_id one level deep).

    Precedence:
        1. envelope['correlation_id']                    (top-level set)
        2. envelope['envelope']['correlation_id']        (Day-7 wrapped form)
        3. envelope['event_id']                          (Day-7 PK; ≈ correlation)
        4. f'corr-{uuid4()}'                             (fresh; better than None)

    The fresh-UUID fallback at (4) still ties this Lambda's internal logs
    together for the single invocation. It can't be joined back to the
    upstream — but it's better than emitting unlabelled logs.

    Args:
        event_envelope: the event arg passed to handler, OR a dict already
            unwrapped from event['Records'][i]['body'] / event['detail'].
            Pass None defensively — returns a fresh UUID.

    Returns:
        a non-empty string suitable for logger.set_correlation_id() and
        for use as the SFN execution name suffix.

    Example:
        def handler(event, context):
            corr = get_correlation_id(event)
            logger.set_correlation_id(corr)
            ...
    """
    if not isinstance(event_envelope, dict):
        return f"corr-{uuid.uuid4()}"

    # Step 1: top-level correlation_id
    corr = event_envelope.get("correlation_id")
    if isinstance(corr, str) and corr:
        return corr

    # Step 2: wrapped envelope (Day-7 producer form)
    inner = event_envelope.get("envelope")
    if isinstance(inner, dict):
        corr = inner.get("correlation_id")
        if isinstance(corr, str) and corr:
            return corr

    # Step 3: event_id (Day-7 stream PK — unique per record)
    eid = event_envelope.get("event_id")
    if isinstance(eid, str) and eid:
        return eid

    # Step 4: fresh UUID — better than nothing
    return f"corr-{uuid.uuid4()}"


# ──────────────────────────────────────────────────────────────────────────
# Flush-early helper
# ──────────────────────────────────────────────────────────────────────────
def flush_metrics_early(metrics: Metrics) -> None:
    """
    Force an EMF metric emit BEFORE a timeout-risk operation.

    The default powertools.Metrics.log_metrics decorator emits the EMF
    block on handler exit. If the handler hits Lambda's hard timeout
    (e.g. invoke_endpoint waits 35s on a cold SageMaker endpoint that
    takes 50s), the decorator never runs → the metrics for THIS invocation
    are lost. Dashboards then show false silence: "no records processed".

    Calling flush_metrics_early(metrics) emits whatever metrics have been
    added so far. Subsequent add_metric() calls accumulate again for the
    next emit (on handler exit, if it reaches it).

    USE BEFORE:
        - sagemaker_runtime.invoke_endpoint(...)        (predict Lambda)
        - bedrock_runtime.invoke_model(...)              (bedrock_enrich Lambda)
        - Any synchronous boto3 call with > 10s read_timeout

    DON'T use:
        - On every add_metric — defeats the async-batching benefit.
        - Before fast operations (< 1s) — adds CW Logs write overhead unnecessarily.

    Args:
        metrics: the powertools.Metrics instance returned by get_metrics()
    """
    metrics.flush_metrics()


# ──────────────────────────────────────────────────────────────────────────
# Defensive sanity check — module import
# ──────────────────────────────────────────────────────────────────────────
# If this module fails to import, every Lambda fails to start. Catch the
# common cause (missing powertools) with a clearer error message at the
# top — Lambda's stderr will surface it.
if __name__ == "__main__":      # pragma: no cover
    print(f"observability.py loaded. NAMESPACE={NAMESPACE}")
    print(f"powertools versions:")
    import aws_lambda_powertools
    print(f"  aws-lambda-powertools=={aws_lambda_powertools.__version__}")
    print("get_correlation_id smoke tests:")
    print(f"  empty dict          → {get_correlation_id({})!r}")
    print(f"  {{event_id: x}}      → {get_correlation_id({'event_id': 'x'})!r}")
    print(f"  {{correlation_id:y}} → {get_correlation_id({'correlation_id': 'y'})!r}")
    print(f"  None               → {get_correlation_id(None)!r}")
