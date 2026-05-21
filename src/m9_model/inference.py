"""
src/m9_model/inference.py — SageMaker scikit-learn inference handler.

This file gets packaged INSIDE the model.tar.gz that SageMaker hosts. The
scikit-learn inference container looks for this exact filename and calls
the four functions below.

NOT a Lambda. Don't deploy as one. This runs inside the SageMaker container.

Input shape (from wrapper Lambda):
    {"booking_id": str, "fare_amount": float,
     "refund_lag_hours": float, "prior_cancels": int}

Output shape (returned to wrapper Lambda):
    {"risk_score": 0..1, "confidence": 0..1, "model_version": str}
"""
from __future__ import annotations

import json
import os
from typing import Any


MODEL_VERSION = "v1.2.3"


def model_fn(model_dir: str) -> Any:
    """Load the joblib-serialised model from model_dir at container start."""
    import joblib
    return joblib.load(os.path.join(model_dir, "model.joblib"))


def input_fn(request_body: str | bytes, request_content_type: str) -> dict:
    """Parse the inbound JSON body."""
    if request_content_type != "application/json":
        raise ValueError(f"Unsupported content_type: {request_content_type}")
    if isinstance(request_body, bytes):
        request_body = request_body.decode("utf-8")
    return json.loads(request_body)


def predict_fn(input_data: dict, model: Any) -> dict:
    """Map 4 features → risk_score + confidence + model_version.

    Lab calibration intent:
      - Extreme features (high fare OR very-immediate / very-late refund_lag
        OR many prior_cancels) → HIGH CONFIDENCE
      - Mid-range features → LOW CONFIDENCE

    Risk score itself comes from the LR; confidence is deterministic from
    feature distance-from-centre.
    """
    fare_amount = float(input_data.get("fare_amount", 0.0))
    refund_lag_hours = float(input_data.get("refund_lag_hours", 0.0))
    prior_cancels = float(input_data.get("prior_cancels", 0))

    # Risk score from the model (LR was trained on 4 normalised features)
    X = [[
        min(fare_amount / 5000.0, 1.0),
        min(refund_lag_hours / 168.0, 1.0),   # cap at 1 week
        min(prior_cancels / 10.0, 1.0),
        1.0 if prior_cancels > 0 else 0.0,
    ]]
    risk_score = float(model.predict_proba(X)[0][1])

    # Confidence: deterministic from feature ambiguity.
    # Distance from "ambiguous middle" → confidence.
    fare_ext = abs(fare_amount - 2500.0) / 2500.0    # 0 at middle, 1 at extreme
    lag_ext = abs(refund_lag_hours - 24.0) / 24.0    # 0 near 24h, 1 at ext
    prior_signal = 1.0 if prior_cancels in (0, 5) else 0.3   # 0/5 = clear, 1 = ambiguous

    # Combine — emphasis on whichever dimension is most extreme
    extremity = max(fare_ext, lag_ext, prior_signal)
    confidence = min(0.95, 0.40 + 0.55 * extremity)

    return {
        "risk_score":    round(risk_score, 4),
        "confidence":    round(confidence, 4),
        "model_version": MODEL_VERSION,
    }


def output_fn(prediction: dict, response_content_type: str) -> tuple[str, str]:
    """Serialise the prediction back to JSON."""
    if response_content_type != "application/json":
        raise ValueError(f"Unsupported accept: {response_content_type}")
    return json.dumps(prediction), response_content_type
