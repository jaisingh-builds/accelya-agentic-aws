#!/usr/bin/env bash
# Day 10 EOD cleanup — preserves dashboard / alarms / SNS / IAM (Day 11 reuses);
# only removes the X-Ray sampling rule override + verifies invariants.
#
# Usage:
#   bash scripts/cleanup_module10.sh <learner>

set -euo pipefail
LEARNER="${1:-${LEARNER:-trainer}}"
REGION="${AWS_REGION:-ap-south-1}"

LAMBDAS=(
  "accelya-validator-${LEARNER}" "accelya-lander-${LEARNER}"
  "accelya-chunker-${LEARNER}" "accelya-dlq-replayer-${LEARNER}"
  "accelya-etl-json-to-parquet-${LEARNER}"
  "accelya-producer-${LEARNER}" "accelya-consumer-${LEARNER}"
  "accelya-bedrock-enrich-${LEARNER}" "accelya-persist-enriched-${LEARNER}"
  "accelya-predict-cancel-risk-${LEARNER}"
)

echo "─── 1. Remove X-Ray sampling override ───"
RULE_ARN=$(aws xray get-sampling-rules --region "$REGION" \
  --query "SamplingRuleRecords[?SamplingRule.RuleName=='accelya-lab-trace-all-${LEARNER}'].SamplingRule.RuleARN" \
  --output text 2>/dev/null || echo "")
if [[ -n "$RULE_ARN" && "$RULE_ARN" != "None" ]]; then
  aws xray delete-sampling-rule --rule-arn "$RULE_ARN" --region "$REGION"
  echo "  ✓ Removed accelya-lab-trace-all-${LEARNER}"
else
  echo "  ✓ Override not present (already cleaned)"
fi

echo "─── 2. Verify 10 Lambdas Active ───"
ACTIVE=0; MISSING=0
for FN in "${LAMBDAS[@]}"; do
  STATE=$(aws lambda get-function --function-name "$FN" --region "$REGION" \
    --query 'Configuration.State' --output text 2>/dev/null || echo "MISSING")
  if [[ "$STATE" == "Active" ]]; then ACTIVE=$((ACTIVE+1)); else MISSING=$((MISSING+1)); fi
done
echo "  Lambdas Active: $ACTIVE / 10 (missing $MISSING)"

echo "─── 3. Verify log retention 14d on all 10 ───"
OK=0; BAD=0
for FN in "${LAMBDAS[@]}"; do
  RET=$(aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/$FN" \
    --region "$REGION" --query 'logGroups[0].retentionInDays' --output text 2>/dev/null || echo "")
  if [[ "$RET" == "14" ]]; then OK=$((OK+1)); else BAD=$((BAD+1)); echo "  ✗ $FN → ${RET:-NEVER_EXPIRE}"; fi
done
echo "  Retention 14d: $OK / 10"

echo "─── 4. Verify TracingConfig Active on all 10 ───"
ACT=0; PT=0
for FN in "${LAMBDAS[@]}"; do
  MODE=$(aws lambda get-function-configuration --function-name "$FN" --region "$REGION" \
    --query 'TracingConfig.Mode' --output text 2>/dev/null || echo "")
  if [[ "$MODE" == "Active" ]]; then ACT=$((ACT+1)); else PT=$((PT+1)); fi
done
echo "  TracingConfig Active: $ACT / 10 (PassThrough: $PT)"

echo ""
echo "Day-10 cleanup complete. Dashboard / alarms / SNS / IAM policy version PRESERVED for Day 11."
