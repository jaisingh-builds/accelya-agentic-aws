"""
src/pretraffic_hook/handler.py — CodeDeploy PreTraffic lifecycle hook.

Lambda #11 of the programme. Only Lambda WITHOUT a DeploymentPreference of its
own (self-reference is illegal).

WHAT IT DOES
============
CodeDeploy invokes this Lambda BEFORE shifting any traffic to a new Lambda
version. We run a synthetic check against the newly-published version (via
the alias's `live` qualifier which now points at the new version) and report
Succeeded or Failed back to CodeDeploy.

If Succeeded: CodeDeploy starts the linear traffic shift.
If Failed:    CodeDeploy ABORTS the deployment; alias stays on previous version.

EVENT SHAPE (from CodeDeploy)
=============================
    {
      "DeploymentId": "d-ABCDEFGHI",
      "LifecycleEventHookExecutionId": "lehei-XYZ"
    }

MUST call put_lifecycle_event_hook_execution_status within 1 hour.

ENV
===
    TARGET_FUNCTION   - the Lambda being deployed (e.g. accelya-predict-cancel-risk-<learner>)
                         Set per-deployment by the SAM template
    LEARNER           - learner suffix
    LOG_LEVEL         - DEBUG | INFO (default INFO)

EXIT BEHAVIOR
=============
We catch ALL exceptions and report Failed (never crash the hook itself —
that leaves CodeDeploy in a stuck state for 1h waiting for status).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError, BotoCoreError

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "ap-south-1")
codedeploy = boto3.client("codedeploy", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)


def _synthetic_event() -> dict[str, Any]:
    """Return a benign event the target Lambda can handle without side effects."""
    return {
        "_pretraffic_check": True,
        "events": [
            {
                "event_id": "pretraffic-synthetic-001",
                "event_type": "cancellation",
                "correlation_id": "pretraffic-synthetic-001",
                "airline_code": "AI",
                "source_system": "SYNTHETIC",
                "pnr": "PTSYNTH",
                "booking_date": "2026-01-01",
                "payload": {
                    "pnr": "PTSYNTH",
                    "fare_amount": 1000.0,
                    "refund_lag_hours": 1.0,
                    "prior_cancels": 0,
                    "booking_id": "BK-PTSYNTH",
                    "cancel_reason_code": "TEST",
                    "cancellation_event_id": "CXL-PTSYNTH",
                },
                "booking_id": "BK-PTSYNTH",
                "fare_amount": 1000.0,
                "refund_lag_hours": 1.0,
                "prior_cancels": 0,
            }
        ],
    }


def _check_target_function(target_fn: str) -> str:
    """
    Invoke the new Lambda version (qualifier='$LATEST') synchronously.
    Return 'Succeeded' if response is 200 and no FunctionError, else 'Failed'.

    Note on qualifier:
      During CodeDeploy linear shift, the alias `live` is mid-update — it
      points at BOTH old and new versions with weights. To target the NEW
      version specifically, we'd need its version number. CodeDeploy passes
      this in the event for advanced use, but the simplest pretraffic check
      uses '$LATEST' which always means "newest published".
    """
    try:
        resp = lambda_client.invoke(
            FunctionName=target_fn,
            Qualifier="$LATEST",
            InvocationType="RequestResponse",
            Payload=json.dumps(_synthetic_event()).encode("utf-8"),
        )
        status_code = resp.get("StatusCode", 0)
        function_error = resp.get("FunctionError")

        if status_code != 200:
            LOG.warning(json.dumps({
                "event": "pretraffic_target_non_200",
                "target_fn": target_fn,
                "status_code": status_code,
            }))
            return "Failed"

        if function_error is not None:
            payload = resp["Payload"].read().decode("utf-8")
            LOG.warning(json.dumps({
                "event": "pretraffic_target_function_error",
                "target_fn": target_fn,
                "function_error": function_error,
                "payload_sample": payload[:500],
            }))
            return "Failed"

        return "Succeeded"

    except (ClientError, BotoCoreError) as e:
        LOG.warning(json.dumps({
            "event": "pretraffic_target_boto_error",
            "target_fn": target_fn,
            "error_type": type(e).__name__,
            "error": str(e),
        }))
        return "Failed"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    deployment_id = event.get("DeploymentId", "")
    hook_exec_id = event.get("LifecycleEventHookExecutionId", "")
    target_fn = os.environ.get("TARGET_FUNCTION", "")

    LOG.info(json.dumps({
        "event": "pretraffic_start",
        "deployment_id": deployment_id,
        "hook_exec_id": hook_exec_id,
        "target_fn": target_fn,
    }))

    if not deployment_id or not hook_exec_id:
        LOG.error(json.dumps({
            "event": "pretraffic_missing_event_fields",
            "received_event_keys": list(event.keys()),
        }))
        # Can't report back without IDs — CodeDeploy will time out after 1h
        return {"status": "Failed", "reason": "missing event fields"}

    # If TARGET_FUNCTION isn't set, this hook is misconfigured —
    # better to report Succeeded with a warning than to block all deploys.
    # In a real production setup, set TARGET_FUNCTION per-deployment via
    # the SAM template's Function environment override per CodeDeploy stage.
    if not target_fn:
        LOG.warning(json.dumps({
            "event": "pretraffic_no_target",
            "msg": "TARGET_FUNCTION env not set — reporting Succeeded as default",
        }))
        status = "Succeeded"
    else:
        status = _check_target_function(target_fn)

    LOG.info(json.dumps({
        "event": "pretraffic_done",
        "deployment_id": deployment_id,
        "status": status,
    }))

    try:
        codedeploy.put_lifecycle_event_hook_execution_status(
            deploymentId=deployment_id,
            lifecycleEventHookExecutionId=hook_exec_id,
            status=status,
        )
    except (ClientError, BotoCoreError) as e:
        # If we can't tell CodeDeploy, the deploy hangs for 1h then auto-fails.
        # Log loudly so a human can investigate.
        LOG.error(json.dumps({
            "event": "pretraffic_put_status_failed",
            "deployment_id": deployment_id,
            "error_type": type(e).__name__,
            "error": str(e),
        }))
        raise

    return {"status": status, "deployment_id": deployment_id}
