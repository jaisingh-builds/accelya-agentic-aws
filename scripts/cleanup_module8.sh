#!/usr/bin/env bash
# Day 8 end-of-module cleanup — PRESERVES EVERYTHING DAY 9+ NEEDS.
#
# Day 8 infrastructure is FULLY KEPT (Day 9 extends it):
#   - 4 Lambdas: producer, consumer, bedrock-enrich, persist-enriched
#   - state machine inference-pipeline-<learner> (Day 9 adds Parallel branch)
#   - ESM event source mapping
#   - SQS DLQ stream-dlq-<learner>
#   - enriched/<learner>/ S3 prefix
#
# What this DOES:
#   - Restores SAMPLE_RATE=10 on bedrock-enrich (in case Lab 3 left it at 1)
#   - Reports Bedrock budget burn (target <=25 of 50 used)
#   - Verifies Lambda count = 9 of 10
#   - Reports state of all M8 resources
#
# Usage:
#   bash scripts/cleanup_module8.sh <learner>

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
PROFILE="apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
ENRICH_FN="accelya-bedrock-enrich-${LEARNER}"
SM_NAME="inference-pipeline-${LEARNER}"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 8 cleanup — restore SAMPLE_RATE, verify resources, no deletions"
echo " Region:  $REGION"
echo " Learner: $LEARNER"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. Restore SAMPLE_RATE=10 on bedrock-enrich ──────────────────────────
echo ""
echo "[1/4] Restore SAMPLE_RATE=10 on $ENRICH_FN"
if aws lambda get-function --function-name "$ENRICH_FN" --region "$REGION" >/dev/null 2>&1; then
  CURRENT_RATE=$(aws lambda get-function-configuration --function-name "$ENRICH_FN" \
    --region "$REGION" --query 'Environment.Variables.SAMPLE_RATE' --output text)
  echo "  Current SAMPLE_RATE: $CURRENT_RATE"
  if [[ "$CURRENT_RATE" != "10" ]]; then
    CURRENT_ENV=$(aws lambda get-function-configuration --function-name "$ENRICH_FN" \
      --region "$REGION" --query 'Environment.Variables' --output json)
    NEW_ENV=$(echo "$CURRENT_ENV" | python3 -c "
import json, sys
env = json.load(sys.stdin)
env['SAMPLE_RATE'] = '10'
print(json.dumps({'Variables': env}))
")
    aws lambda update-function-configuration \
      --function-name "$ENRICH_FN" \
      --environment "$NEW_ENV" \
      --region "$REGION" >/dev/null
    aws lambda wait function-updated-v2 --function-name "$ENRICH_FN" --region "$REGION"
    echo "  ✓ Restored to SAMPLE_RATE=10"
  else
    echo "  ✓ Already at 10"
  fi
else
  echo "  (bedrock-enrich Lambda not deployed yet)"
fi

# ── 2. Lambda + state machine sanity ─────────────────────────────────────
echo ""
echo "[2/4] M8 resource health check"
for FN in accelya-producer-${LEARNER} accelya-consumer-${LEARNER} \
          accelya-bedrock-enrich-${LEARNER} accelya-persist-enriched-${LEARNER}; do
  STATE=$(aws lambda get-function --function-name "$FN" --region "$REGION" \
    --query 'Configuration.State' --output text 2>/dev/null || echo "MISSING")
  printf "  %-50s %s\n" "$FN" "$STATE"
done

SM_ARN=$(aws stepfunctions list-state-machines --region "$REGION" \
  --query "stateMachines[?name=='$SM_NAME'].stateMachineArn" --output text 2>/dev/null || echo "")
if [[ -n "$SM_ARN" ]]; then
  printf "  %-50s %s\n" "$SM_NAME" "PRESENT"
else
  printf "  %-50s %s\n" "$SM_NAME" "MISSING"
fi

# ── 3. ESM sanity ───────────────────────────────────────────────────────
echo ""
echo "[3/4] ESM (Event Source Mapping) sanity"
ESM_INFO=$(aws lambda list-event-source-mappings \
  --function-name accelya-consumer-${LEARNER} --region "$REGION" \
  --query 'EventSourceMappings[].[UUID,State,BatchSize,FunctionResponseTypes]' \
  --output text 2>/dev/null || echo "")
if [[ -n "$ESM_INFO" ]]; then
  echo "  $ESM_INFO"
else
  echo "  (no ESM wired yet — Lab 2 step 1)"
fi

# ── 4. Bedrock budget + Lambda count ─────────────────────────────────────
echo ""
echo "[4/4] Budget summary"
LAMBDA_COUNT=$(aws lambda list-functions --region "$REGION" \
  --query "length(Functions[?contains(FunctionName,'-${LEARNER}')])" --output text)
echo "  Lambdas for $LEARNER: $LAMBDA_COUNT of 10"

START=$(date -u -v-7d +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u --date='7 days ago' +%Y-%m-%dT%H:%M:%S)
END=$(date -u +%Y-%m-%dT%H:%M:%S)
INVOCATIONS=$(aws cloudwatch get-metric-statistics \
  --namespace AWS/Bedrock \
  --metric-name Invocations \
  --dimensions Name=ModelId,Value=$PROFILE \
  --start-time $START --end-time $END --period 604800 \
  --statistics Sum --region "$REGION" \
  --query 'Datapoints[0].Sum' --output text 2>/dev/null || echo "0")
echo "  Bedrock invocations (last 7d): ${INVOCATIONS:-0} of 50 cap"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ Day 8 cleanup complete — all programme artefacts preserved"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Day 9 prerequisites:"
echo "  - 4 M8 Lambdas Active"
echo "  - inference-pipeline-$LEARNER state machine PRESENT"
echo "  - ESM Active on accelya-consumer-$LEARNER"
echo "  - SAMPLE_RATE=10 on bedrock-enrich"
echo "  - .windsurfrules v5 committed (Day 9 promotes to v6)"
