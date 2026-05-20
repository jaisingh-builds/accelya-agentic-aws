#!/usr/bin/env bash
# Day 8 Lab 1 — deploy `inference-pipeline-<learner>` state machine.
#
# Renders infra/inference-pipeline.asl.json via envsubst, validates,
# creates/updates the state machine, and patches the consumer Lambda's
# SM_ARN env var.
#
# Prerequisites:
#   - 4 M8 Lambdas already deployed (run deploy_m8_lambdas.sh first)
#   - SFN role accelya-pipeline-sfn-role exists (from Day 5 bootstrap)
#
# Usage:
#   bash scripts/deploy_m8_state_machine.sh <learner>

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

SM_NAME="inference-pipeline-${LEARNER}"
CONSUMER_FN="accelya-consumer-${LEARNER}"
SFN_ROLE_NAME="${SFN_ROLE_NAME:-accelya-m5-sfn-${LEARNER}-role}"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
STARTER_REPO="$( cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
ASL_TEMPLATE="$STARTER_REPO/infra/inference-pipeline.asl.json"
ASL_RENDERED="/tmp/inference-pipeline-${LEARNER}.rendered.asl.json"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 8 Lab 1 — deploy state machine"
echo " Region:    $REGION"
echo " Name:      $SM_NAME"
echo " SFN role:  $SFN_ROLE_NAME"
echo "═══════════════════════════════════════════════════════════════"

# ── Pre-flight: SFN role exists ──────────────────────────────────────────
if ! aws iam get-role --role-name "$SFN_ROLE_NAME" >/dev/null 2>&1; then
  echo "❌ SFN role missing: $SFN_ROLE_NAME"
  echo "   Day 5 bootstrap (30_create_m5_pipeline.sh) creates this role."
  exit 1
fi
SFN_ROLE_ARN=$(aws iam get-role --role-name "$SFN_ROLE_NAME" --query 'Role.Arn' --output text)

# Extend the SFN role to invoke M8 Lambdas
SFN_M8_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeM8Lambdas",
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": [
        "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:accelya-bedrock-enrich-${LEARNER}",
        "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:accelya-persist-enriched-${LEARNER}"
      ]
    }
  ]
}
EOF
)
echo "$SFN_M8_POLICY" > /tmp/m8-sfn-policy.json
aws iam put-role-policy \
  --role-name "$SFN_ROLE_NAME" \
  --policy-name "M8SfnInvokePolicy" \
  --policy-document "file:///tmp/m8-sfn-policy.json"
echo "  ✓ M8SfnInvokePolicy attached to $SFN_ROLE_NAME"

# ── Render ASL via envsubst ──────────────────────────────────────────────
export AWS_REGION="$REGION"
export AWS_ACCOUNT_ID="$ACCOUNT_ID"
export LEARNER

envsubst < "$ASL_TEMPLATE" > "$ASL_RENDERED"

# Validate
VAL=$(aws stepfunctions validate-state-machine-definition \
  --region "$REGION" \
  --definition "file://$ASL_RENDERED" \
  --query 'result' --output text)
if [[ "$VAL" != "OK" ]]; then
  echo "❌ ASL validation failed: $VAL"
  exit 1
fi
echo "✓ ASL validates"

# ── Create or update state machine ───────────────────────────────────────
SM_ARN=$(aws stepfunctions list-state-machines --region "$REGION" \
  --query "stateMachines[?name=='$SM_NAME'].stateMachineArn" --output text 2>/dev/null || echo "")

if [[ -n "$SM_ARN" ]]; then
  echo "  ✓ State machine exists; updating definition..."
  aws stepfunctions update-state-machine \
    --state-machine-arn "$SM_ARN" \
    --definition "file://$ASL_RENDERED" \
    --role-arn "$SFN_ROLE_ARN" \
    --region "$REGION" >/dev/null
else
  echo "  → Creating state machine..."
  SM_ARN=$(aws stepfunctions create-state-machine \
    --name "$SM_NAME" \
    --definition "file://$ASL_RENDERED" \
    --role-arn "$SFN_ROLE_ARN" \
    --type STANDARD \
    --tags key=programme,value=accelya-agentic-aws key=module,value=m8 \
    --region "$REGION" --query stateMachineArn --output text)
fi
echo "  State machine ARN: $SM_ARN"

# ── Patch the consumer's SM_ARN env var ──────────────────────────────────
echo ""
echo "Patching consumer Lambda SM_ARN..."
CURRENT_ENV=$(aws lambda get-function-configuration --function-name "$CONSUMER_FN" \
  --region "$REGION" --query 'Environment.Variables' --output json)
NEW_ENV=$(echo "$CURRENT_ENV" | python3 -c "
import json, sys
env = json.load(sys.stdin)
env['SM_ARN'] = '$SM_ARN'
print(json.dumps({'Variables': env}))
")
aws lambda update-function-configuration \
  --function-name "$CONSUMER_FN" \
  --environment "$NEW_ENV" \
  --region "$REGION" >/dev/null
aws lambda wait function-updated-v2 --function-name "$CONSUMER_FN" --region "$REGION"
echo "  ✓ Consumer SM_ARN updated"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ State machine deployed and consumer patched"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Captured: SM_ARN=$SM_ARN"
echo ""
echo "Next: Lab 2 — wire the ESM (see deploy_m8_lambdas.sh output)"
