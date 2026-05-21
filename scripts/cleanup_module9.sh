#!/usr/bin/env bash
# Day 9 end-of-module cleanup — DELETES the SageMaker endpoint stack
# (sandbox cap = 1), preserves everything else.
#
# What this DELETES (sandbox-cap enforcement):
#   - Endpoint           accelya-cancel-risk-<learner>
#   - Endpoint config    accelya-cancel-risk-config-<learner>
#   - Model              accelya-cancel-risk-model-<learner>
#
# What this PRESERVES (Day 10+ needs):
#   - All 10 Lambdas (final cap)
#   - State machine with Parallel + Choice (Day 10 dashboards inherit)
#   - SQS model-review-queue-<learner>
#   - DLQ stream-dlq-<learner>
#   - All Day-5/6/7/8 resources
#   - IAM accelya-sagemaker-role-<learner> (cheap; useful for re-deploy)
#
# Usage:
#   bash scripts/cleanup_module9.sh <learner>

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
PROFILE="apac.anthropic.claude-3-5-sonnet-20241022-v2:0"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 9 cleanup — DELETE endpoint (sandbox cap), preserve the rest"
echo " Region:  $REGION"
echo " Learner: $LEARNER"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. Delete endpoint stack (delegate to reset script) ──────────────────
echo ""
echo "[1/4] Deleting endpoint stack via reset_module9_endpoint.sh"
bash "$SCRIPT_DIR/reset_module9_endpoint.sh" "$LEARNER"

# ── 2. Lambda count check (target: 10) ───────────────────────────────────
echo ""
echo "[2/4] Lambda count check (target: 10 of 10 final cap)"
LAMBDA_COUNT=$(aws lambda list-functions --region "$REGION" \
  --query "length(Functions[?contains(FunctionName,'-${LEARNER}')])" --output text)
echo "  Lambdas for $LEARNER: $LAMBDA_COUNT of 10"

if [[ "$LAMBDA_COUNT" != "10" ]]; then
  echo "  ⚠️  Expected 10 Lambdas; got $LAMBDA_COUNT. Investigate:"
  aws lambda list-functions --region "$REGION" \
    --query "Functions[?contains(FunctionName,'-${LEARNER}')].FunctionName" --output text | tr '\t' '\n'
fi

# ── 3. State machine sanity ──────────────────────────────────────────────
echo ""
echo "[3/4] State machine: inference-pipeline-$LEARNER"
SM_ARN=$(aws stepfunctions list-state-machines --region "$REGION" \
  --query "stateMachines[?name=='inference-pipeline-$LEARNER'].stateMachineArn" --output text 2>/dev/null || echo "")
if [[ -n "$SM_ARN" ]]; then
  echo "  ✓ PRESENT — $SM_ARN"
  # Confirm Parallel + Choice are in the definition
  DEFINITION=$(aws stepfunctions describe-state-machine --state-machine-arn "$SM_ARN" \
    --region "$REGION" --query 'definition' --output text)
  if echo "$DEFINITION" | grep -q '"EnrichInParallel"'; then
    echo "  ✓ EnrichInParallel present"
  else
    echo "  ⚠️  EnrichInParallel missing — ASL was not updated to Day-9 shape"
  fi
  if echo "$DEFINITION" | grep -q '"HasLowConfidence"'; then
    echo "  ✓ HasLowConfidence Choice present"
  else
    echo "  ⚠️  HasLowConfidence Choice missing"
  fi
fi

# ── 4. Bedrock budget summary ────────────────────────────────────────────
echo ""
echo "[4/4] Bedrock budget summary"
START=$(date -u -v-30d +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u --date='30 days ago' +%Y-%m-%dT%H:%M:%S)
END=$(date -u +%Y-%m-%dT%H:%M:%S)
INVOCATIONS=$(aws cloudwatch get-metric-statistics \
  --namespace AWS/Bedrock --metric-name Invocations \
  --dimensions Name=ModelId,Value=$PROFILE \
  --start-time $START --end-time $END --period 2592000 \
  --statistics Sum --region "$REGION" \
  --query 'Datapoints[0].Sum' --output text 2>/dev/null || echo "0")
echo "  Bedrock invocations (last 30d): ${INVOCATIONS:-0} of 50 cap"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ Day 9 cleanup complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Day 10 prerequisites:"
echo "  - 10 Lambdas Active (final cap)"
echo "  - inference-pipeline-$LEARNER state machine with Parallel + Choice"
echo "  - model-review-queue-$LEARNER SQS preserved"
echo "  - stream-dlq-$LEARNER preserved"
echo "  - SageMaker endpoint deleted (sandbox cap = 1)"
echo "  - .windsurfrules v6 committed (Day 10 promotes to v7)"
