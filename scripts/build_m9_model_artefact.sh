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

# Ensure scikit-learn + joblib are installed on the local machine.
# Use the SAME python3 binary the heredoc will use, otherwise --user installs
# may land in a different site-packages than the heredoc's interpreter sees.
PY="${PYTHON:-python3}"

# Skip if model already in S3 — the artefact is shared across the cohort
# (trained once, hosted by each learner's own endpoint). Override via
# FORCE_REBUILD=1 if you've patched src/m9_model/inference.py and need to
# republish.
if [[ "${FORCE_REBUILD:-0}" != "1" ]]; then
  if aws s3 ls "s3://${BUCKET}/${S3_KEY}" --region "$REGION" >/dev/null 2>&1; then
    echo "  ✓ Model artefact already at s3://${BUCKET}/${S3_KEY}"
    echo "    (Shared across cohort; built once. Set FORCE_REBUILD=1 to republish.)"
    exit 0
  fi
fi

ensure_pkg() {
  local pkg="$1"
  if "$PY" -c "import $pkg" 2>/dev/null; then return 0; fi
  echo "  → installing $pkg ..."
  "$PY" -m pip install --quiet "$pkg" 2>/dev/null \
    || "$PY" -m pip install --user --quiet "$pkg" 2>/dev/null \
    || "$PY" -m pip install --break-system-packages --quiet "$pkg" 2>/dev/null \
    || { echo "❌ Could not install $pkg with $PY"; return 1; }
}

ensure_pkg scikit_learn || ensure_pkg sklearn || { echo "❌ install sklearn failed"; exit 1; }
ensure_pkg joblib       || { echo "❌ install joblib failed"; exit 1; }
ensure_pkg numpy        || { echo "❌ install numpy failed"; exit 1; }

# HARD-FAIL if the heredoc python (same $PY) still can't see them
"$PY" -c "import sklearn, joblib, numpy" || {
  echo "❌ $PY cannot import sklearn/joblib/numpy after install. Aborting build."
  echo "   Try setting PYTHON env var to a working python3 with these libs."
  exit 1
}
echo "  ✓ $PY + sklearn + joblib + numpy ready"

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
# SageMaker's prebuilt scikit-learn container looks for inference.py UNDER code/
# (set as SAGEMAKER_PROGRAM at model creation), NOT at the tarball root. The
# model.joblib stays at the root (model_dir). Layout:
#   model.tar.gz
#   ├── model.joblib       ← loaded by model_fn(model_dir)
#   └── code/
#       └── inference.py    ← SAGEMAKER_PROGRAM target
mkdir -p "$BUILD_DIR/code"
cp "$INFERENCE_SRC" "$BUILD_DIR/code/inference.py"

"$PY" - <<'PY' || { echo "❌ model training/serialise step FAILED. Aborting build."; exit 1; }
import os, sys
try:
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
except ImportError as e:
    print(f"  ❌ import failed inside heredoc: {e}", file=sys.stderr)
    print(f"  python: {sys.executable}", file=sys.stderr)
    print(f"  sys.path: {sys.path}", file=sys.stderr)
    sys.exit(1)

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

# Hard verify on disk
assert os.path.exists(out), f"model.joblib NOT written to {out}"
size = os.path.getsize(out)
assert size > 100, f"model.joblib suspiciously small: {size} bytes"

print(f"  ✓ model.joblib written: {size} bytes")
print(f"  ✓ training set: X.shape={X.shape}, positive_rate={y.mean():.3f}")
print(f"  ✓ classes: {m.classes_}, coef: {m.coef_[0].round(3).tolist()}")
print(f"  ✓ sklearn version (must match container's): {__import__('sklearn').__version__}")
print(f"  ✓ joblib version: {joblib.__version__}")
PY

# ── 2. Smoke-test the inference handler locally ──────────────────────────
echo ""
echo "[2/4] Smoke-test inference.py locally"
"$PY" - <<'PY' || { echo "❌ inference.py smoke-test failed. Aborting."; exit 1; }
import sys, os, json
sys.path.insert(0, "/tmp/m9-model/code")
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
echo "[3/4] Build model.tar.gz (layout: model.joblib + code/inference.py)"
( cd "$BUILD_DIR" && tar -czf "$TARBALL" model.joblib code/inference.py )
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
echo "  bash scripts/deploy_m9_endpoint.sh <your-name>"
echo "Or full Day-9 stack (endpoint + wrapper + IAM + SQS + ASL update):"
echo "  bash scripts/deploy_m9_full_stack.sh <your-name>"
