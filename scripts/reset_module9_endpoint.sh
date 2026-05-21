#!/usr/bin/env bash
# Day 9 — IDEMPOTENT reset/teardown of the SageMaker endpoint stack.
#
# Used in two scenarios:
#   1. Lab 1 step 6 (rare) — to start over if config went wrong
#   2. Lab 3 step 6 (MANDATORY) — sandbox cap = 1; must delete by EOD
#
# Order of deletion:
#   1. Endpoint           (delete-endpoint)
#   2. Endpoint config    (delete-endpoint-config)
#   3. Model              (delete-model)
#   IAM role is preserved (cheap, no cap, useful for re-deploy)
#
# Usage:
#   bash scripts/reset_module9_endpoint.sh <learner>

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
MODEL_NAME="accelya-cancel-risk-model-${LEARNER}"
CONFIG_NAME="accelya-cancel-risk-config-${LEARNER}"
ENDPOINT_NAME="accelya-cancel-risk-${LEARNER}"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 9 reset — delete endpoint + config + model"
echo " Region: $REGION  Learner: $LEARNER"
echo "═══════════════════════════════════════════════════════════════"

# 1. Endpoint
echo ""
echo "[1/3] Endpoint: $ENDPOINT_NAME"
if aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" \
     --region "$REGION" >/dev/null 2>&1; then
  aws sagemaker delete-endpoint --endpoint-name "$ENDPOINT_NAME" --region "$REGION"
  echo "  → delete-endpoint initiated"
  # Poll for actual removal (10s intervals, up to 5 min)
  for i in $(seq 1 30); do
    if ! aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" \
         --region "$REGION" >/dev/null 2>&1; then
      echo "  ✓ Endpoint deleted"
      break
    fi
    sleep 10
  done
else
  echo "  (gone) $ENDPOINT_NAME"
fi

# 2. Endpoint config
echo ""
echo "[2/3] Endpoint config: $CONFIG_NAME"
if aws sagemaker describe-endpoint-config --endpoint-config-name "$CONFIG_NAME" \
     --region "$REGION" >/dev/null 2>&1; then
  aws sagemaker delete-endpoint-config --endpoint-config-name "$CONFIG_NAME" --region "$REGION"
  echo "  ✓ Config deleted"
else
  echo "  (gone)"
fi

# 3. Model
echo ""
echo "[3/3] Model: $MODEL_NAME"
if aws sagemaker describe-model --model-name "$MODEL_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws sagemaker delete-model --model-name "$MODEL_NAME" --region "$REGION"
  echo "  ✓ Model deleted"
else
  echo "  (gone)"
fi

# Verify the sandbox cap is clean
echo ""
echo "Sandbox cap verification — endpoints remaining for $LEARNER:"
COUNT=$(aws sagemaker list-endpoints --region "$REGION" \
  --query "length(Endpoints[?contains(EndpointName,'$LEARNER')])" --output text)
echo "  Endpoints: $COUNT (target: 0)"

if [[ "$COUNT" == "0" ]]; then
  echo ""
  echo "═══════════════════════════════════════════════════════════════"
  echo " ✅ Day 9 endpoint stack cleanly removed (sandbox cap restored)"
  echo "═══════════════════════════════════════════════════════════════"
else
  echo ""
  echo "⚠️  $COUNT endpoint(s) still present for $LEARNER. Investigate manually:"
  echo "   aws sagemaker list-endpoints --region $REGION \\"
  echo "     --query \"Endpoints[?contains(EndpointName,'$LEARNER')]\""
fi
