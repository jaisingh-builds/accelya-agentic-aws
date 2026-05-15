#!/usr/bin/env bash
# Day 5 end-of-module cleanup.
#
# DELETES (Lab 2 lab-only resources):
#   - m5-test-validator-<learner>            (Lambda)
#   - m5-test-validator-<learner> ESM        (Event source mapping)
#   - m5-test-queue-<learner>                (SQS queue)
#   - m5-test-dlq-<learner>                  (SQS DLQ)
#
# PRESERVES (programme artefacts; carry forward to Day 6+):
#   - accelya-chunker-<learner>              (Lambda)
#   - accelya-validator-<learner>            (Lambda)
#   - accelya-lander-<learner>               (Lambda)
#   - accelya-dlq-replayer-<learner>         (Lambda)
#   - idempotency_keys_<learner>             (DynamoDB)
#   - validator-pipeline-<learner>           (State machine)
#   - dlq-replayer-<learner>                 (State machine)
#   - accelya-pipeline-escalations-<learner> (SNS topic)
#   - validated/ + quarantine/ S3 paths
#
# Usage:
#   bash scripts/cleanup_module5.sh <learner>
#
# Idempotent — re-running after partial cleanup is safe.

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "═══════════════════════════════════════════════════════════════"
echo " Day 5 cleanup — remove Lab 2 standalone resources"
echo " Region:  $REGION"
echo " Account: $ACCOUNT_ID"
echo " Learner: $LEARNER"
echo "═══════════════════════════════════════════════════════════════"
echo ""

TEST_VALIDATOR="m5-test-validator-${LEARNER}"
TEST_QUEUE="m5-test-queue-${LEARNER}"
TEST_DLQ="m5-test-dlq-${LEARNER}"

# 1. Disable + delete the ESM
echo "[1/4] Removing event source mapping for $TEST_VALIDATOR..."
ESM_UUIDS=$(aws lambda list-event-source-mappings \
    --function-name "$TEST_VALIDATOR" --region "$REGION" \
    --query 'EventSourceMappings[].UUID' --output text 2>/dev/null || echo "")
if [[ -n "$ESM_UUIDS" ]]; then
  for UUID in $ESM_UUIDS; do
    echo "    deleting ESM $UUID..."
    aws lambda delete-event-source-mapping --uuid "$UUID" --region "$REGION" \
      --query 'UUID' --output text >/dev/null || echo "    (already gone)"
  done
  # Give ESM a moment to disengage before queue delete
  sleep 5
else
  echo "    no ESMs found — already clean"
fi

# 2. Delete the test-validator Lambda
echo "[2/4] Deleting Lambda $TEST_VALIDATOR..."
if aws lambda get-function --function-name "$TEST_VALIDATOR" --region "$REGION" >/dev/null 2>&1; then
  aws lambda delete-function --function-name "$TEST_VALIDATOR" --region "$REGION"
  echo "    ✓ deleted"
else
  echo "    (already gone)"
fi

# 3. Delete the test queues
for Q in "$TEST_QUEUE" "$TEST_DLQ"; do
  echo "[3/4] Deleting queue $Q..."
  Q_URL=$(aws sqs get-queue-url --queue-name "$Q" --region "$REGION" \
    --query 'QueueUrl' --output text 2>/dev/null || echo "")
  if [[ -n "$Q_URL" ]]; then
    aws sqs delete-queue --queue-url "$Q_URL" --region "$REGION"
    echo "    ✓ deleted ($Q_URL)"
  else
    echo "    (already gone)"
  fi
done

# 4. Sanity report on remaining Day 5 resources
echo ""
echo "[4/4] Sanity report — programme resources still alive"
echo "    Lambdas:"
for FN in "accelya-chunker-${LEARNER}" "accelya-validator-${LEARNER}" \
          "accelya-lander-${LEARNER}" "accelya-dlq-replayer-${LEARNER}"; do
  STATE=$(aws lambda get-function --function-name "$FN" --region "$REGION" \
    --query 'Configuration.State' --output text 2>/dev/null || echo "MISSING")
  printf "      %-40s %s\n" "$FN" "$STATE"
done
echo "    DynamoDB:"
STATUS=$(aws dynamodb describe-table --table-name "idempotency_keys_${LEARNER}" \
  --region "$REGION" --query 'Table.TableStatus' --output text 2>/dev/null || echo "MISSING")
printf "      %-40s %s\n" "idempotency_keys_${LEARNER}" "$STATUS"
echo "    State machines:"
for SM in "validator-pipeline-${LEARNER}" "dlq-replayer-${LEARNER}"; do
  ARN=$(aws stepfunctions list-state-machines --region "$REGION" \
    --query "stateMachines[?name=='$SM'].stateMachineArn" --output text 2>/dev/null || echo "")
  if [[ -n "$ARN" ]]; then
    printf "      %-40s %s\n" "$SM" "PRESENT"
  else
    printf "      %-40s %s\n" "$SM" "MISSING"
  fi
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ Day 5 cleanup complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Bring forward to Day 6:"
echo "  - validated/<learner>/  S3 prefix      (Glue Crawler input)"
echo "  - idempotency_keys_<learner> table    (carries forward)"
echo "  - .windsurfrules v2                   (Day 6 promotes to v3)"
