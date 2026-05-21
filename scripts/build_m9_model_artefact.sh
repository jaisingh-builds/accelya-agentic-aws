#!/usr/bin/env bash
# Build + upload the Day 9 SageMaker model artefact.
#
# Produces:
#   /tmp/m9-model/model.joblib              ← stub LogisticRegression
#   /tmp/m9-model/inference.py              ← from src/m9_model/inference.py
#   /tmp/m9-model.tar.gz                    ← packaged artefact
#   s3://<bucket>/models/cancel-risk/v1.2.3/model.tar.gz  ← uploaded
#
# Why a stub model:
#   We're teaching the WIRING (endpoint + wrapper + ASL Parallel + Choice),
#   not training a real chargeback-risk classifier. The stub is deterministic
#   on the lab's test inputs so the Lab-3 7-high-conf / 3-low-conf split
#   reproducibly works.
#
# Usage:
#   bash scripts/build_m9_model_artefact.sh           # default bucket + v1.2.3
#   BUCKET_NAME=... MODEL_VERSION=... bash ...        # override
#
# Idempotent — re-running overwrites the S3 object.

set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
BUCKET="${BUCKET_NAME:-accelya-airline-data-ap-south-1}"
MODEL_VERSION="${MODEL_VERSION:-v1.2.3}"
S3_KEY="models/cancel-risk/${MODEL_VERSION}/model.tar.gz"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
STARTER_REPO="$( cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
INFERENCE_SRC="$STARTER_REPO/src/m9_model/inference.py"

BUILD_DIR="/tmp/m9-model"
TARBALL="/tmp/m9-model.tar.gz"

echo "═══════════════════════════════════════════════════════════════"
echo " Build + upload Day 9 model artefact"
echo " Region:  $REGION"
echo " Bucket:  s3://$BUCKET"
echo " Key:     $S3_KEY"
echo "═══════════════════════════════════════════════════════════════"

# ── Pre-flight ───────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 missing"; exit 1
fi

# Ensure scikit-learn + joblib are installed (locally on trainer machine)
if ! python3 -c "import sklearn, joblib" 2>/dev/null; then
  echo "  → installing scikit-learn + joblib locally..."
  pip3 install --user --quiet scikit-learn joblib || {
    echo "❌ pip3 install failed. Try:"
    echo "   pip3 install --break-system-packages scikit-learn joblib"
    exit 1
  }
fi
echo "  ✓ python3 + sklearn + joblib ready"

if [[ ! -f "$INFERENCE_SRC" ]]; then
  echo "❌ Missing inference handler: $INFERENCE_SRC"; exit 1
fi

if ! aws sts get-caller-identity --region "$REGION" >/dev/null 2>&1; then
  echo "❌ AWS creds not set."; exit 1
fi

if ! aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null; then
  echo "❌ Bucket s3://$BUCKET missing. Use 12_bootstrap_shared_aws_resources.sh."
  exit 1
fi

# ── 1. Build the joblib model in a clean dir ─────────────────────────────
echo ""
echo "[1/4] Train + serialise stub LogisticRegression to model.joblib"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cp "$INFERENCE_SRC" "$BUILD_DIR/inference.py"

python3 - <<'PY'
import os
import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

# Synthetic training data shaped to the 4 features in inference.py:
#   [fare_amount/5000, refund_lag/168, prior_cancels/10, has_priors_flag]
rng = np.random.default_rng(20260520)
X = rng.random((2000, 4))
# Synthetic label: high risk when fare is high AND priors exist AND lag is short OR long
y = ((X[:, 0] > 0.5) & (X[:, 3] > 0.5) &
     ((X[:, 1] < 0.2) | (X[:, 1] > 0.6))).astype(int)

m = LogisticRegression(max_iter=1000).fit(X, y)
out = "/tmp/m9-model/model.joblib"
joblib.dump(m, out)
print(f"  ✓ model.joblib written: {os.path.getsize(out)} bytes")
print(f"  ✓ training set: X.shape={X.shape}, positive_rate={y.mean():.3f}")
print(f"  ✓ classes: {m.classes_}, coef: {m.coef_[0].round(3).tolist()}")
PY

# ── 2. Smoke-test the inference handler locally ──────────────────────────
echo ""
echo "[2/4] Smoke-test inference.py locally"
python3 - <<'PY'
import sys, os, json
sys.path.insert(0, "/tmp/m9-model")
import inference

# 1. model_fn loads the joblib
model = inference.model_fn("/tmp/m9-model")
print(f"  ✓ model_fn loaded: {type(model).__name__}")

# 2. input_fn parses JSON
body = json.dumps({
    "booking_id": "BK-TEST", "fare_amount": 4500.0,
    "refund_lag_hours": 0.5, "prior_cancels": 0,
})
parsed = inference.input_fn(body, "application/json")
print(f"  ✓ input_fn parsed: {parsed}")

# 3. predict_fn returns shaped dict
result = inference.predict_fn(parsed, model)
print(f"  ✓ predict_fn returned: {result}")
assert "risk_score" in result, "missing risk_score"
assert "confidence" in result, "missing confidence"
assert "model_version" in result, "missing model_version"

# 4. output_fn serialises
body_out, ct = inference.output_fn(result, "application/json")
print(f"  ✓ output_fn ({ct}): {body_out}")

# 5. Run high-conf / low-conf sample inputs to confirm calibration intent
print("\n  Calibration check (deterministic):")
for label, payload in [
    ("HIGH-fare/IMMEDIATE-refund", {"fare_amount": 4500, "refund_lag_hours": 0.5, "prior_cancels": 0}),
    ("HIGH-fare/LATE-refund",      {"fare_amount": 4500, "refund_lag_hours": 168, "prior_cancels": 5}),
    ("MID-range/AMBIGUOUS",        {"fare_amount": 2200, "refund_lag_hours": 14,  "prior_cancels": 1}),
    ("MID-range/AMBIGUOUS-2",      {"fare_amount": 2400, "refund_lag_hours": 18,  "prior_cancels": 1}),
]:
    r = inference.predict_fn(payload, model)
    flag = "HIGH" if r["confidence"] >= 0.7 else "LOW "
    print(f"    [{flag}] {label:30s} → risk={r['risk_score']:.3f}  confidence={r['confidence']:.3f}")
PY

# ── 3. Tarball it ────────────────────────────────────────────────────────
echo ""
echo "[3/4] Build model.tar.gz"
( cd "$BUILD_DIR" && tar -czf "$TARBALL" inference.py model.joblib )
SIZE=$(du -h "$TARBALL" | cut -f1)
echo "  ✓ $TARBALL ($SIZE)"

echo ""
echo "  Tarball contents:"
tar -tzf "$TARBALL" | sed 's/^/    /'

# ── 4. Upload to S3 ──────────────────────────────────────────────────────
echo ""
echo "[4/4] Upload to s3://$BUCKET/$S3_KEY"
aws s3 cp "$TARBALL" "s3://$BUCKET/$S3_KEY" --region "$REGION"

echo ""
echo "  Verify:"
aws s3 ls "s3://$BUCKET/$S3_KEY" --region "$REGION" | sed 's/^/    /'

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ Model artefact built + uploaded"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Verify from anywhere:"
echo "  aws s3 ls s3://$BUCKET/$S3_KEY --region $REGION"
echo ""
echo "Inspect the tarball contents:"
echo "  aws s3 cp s3://$BUCKET/$S3_KEY /tmp/m9-check.tar.gz --region $REGION"
echo "  tar -tzf /tmp/m9-check.tar.gz"
echo ""
echo "Next: deploy the endpoint"
echo "  bash scripts/deploy_m9_endpoint.sh <learner>"
echo "Or full Day-9 trainer stack:"
echo "  bash trainer-deliverables/46_create_m9_pipeline.sh"
