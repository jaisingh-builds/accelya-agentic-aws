#!/usr/bin/env bash
# Day 8 Lab 1 — deploy the 4 streaming Lambdas:
#   - accelya-producer-<learner>           (bulk PutRecords)
#   - accelya-consumer-<learner>           (THIN, ESM-triggered)
#   - accelya-bedrock-enrich-<learner>     (Step Functions Task; sampled)
#   - accelya-persist-enriched-<learner>   (Step Functions Task; S3 write)
#
# Day 8 also creates one SQS DLQ for ESM OnFailure: stream-dlq-<learner>
#
# Prerequisites:
#   - Day 7 stream + IAM role + idempotency table exist (run 38_create_m7_stream.sh)
#   - .windsurfrules v5 committed
#
# Usage:
#   bash scripts/deploy_m8_lambdas.sh <learner>
#
# Idempotent — re-running updates code + config in place.

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
BUCKET="${BUCKET_NAME:-accelya-airline-data-ap-south-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

STREAM="accelya-bookings-stream-${LEARNER}"
STREAM_ROLE="accelya-stream-role-${LEARNER}"
IDEMP_TABLE="stream_seen_keys_${LEARNER}"
DLQ_NAME="stream-dlq-${LEARNER}"

PRODUCER_FN="accelya-producer-${LEARNER}"
CONSUMER_FN="accelya-consumer-${LEARNER}"
ENRICH_FN="accelya-bedrock-enrich-${LEARNER}"
PERSIST_FN="accelya-persist-enriched-${LEARNER}"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
STARTER_REPO="$( cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
BUILD_DIR="/tmp/m8-build"
ZIP_DIR="/tmp/m8-zips"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 8 Lab 1 — deploy 4 streaming Lambdas + DLQ"
echo " Region:  $REGION"
echo " Bucket:  s3://$BUCKET"
echo " Learner: $LEARNER"
echo "═══════════════════════════════════════════════════════════════"

# ── Pre-flight: Day-7 resources alive ────────────────────────────────────
if ! aws kinesis describe-stream --stream-name "$STREAM" --region "$REGION" >/dev/null 2>&1; then
  echo "❌ Day-7 stream missing: $STREAM"
  echo "   Run: bash scripts/provision_m7_stream.sh $LEARNER"
  exit 1
fi
if ! aws iam get-role --role-name "$STREAM_ROLE" >/dev/null 2>&1; then
  echo "❌ Day-7 stream role missing: $STREAM_ROLE"; exit 1
fi
if ! aws dynamodb describe-table --table-name "$IDEMP_TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo "❌ Day-7 idempotency table missing: $IDEMP_TABLE"; exit 1
fi

STREAM_ROLE_ARN=$(aws iam get-role --role-name "$STREAM_ROLE" --query 'Role.Arn' --output text)
STREAM_ARN=$(aws kinesis describe-stream --stream-name "$STREAM" --region "$REGION" \
  --query 'StreamDescription.StreamARN' --output text)

# ── 1. SQS DLQ for ESM OnFailure ─────────────────────────────────────────
echo ""
echo "[1/6] SQS DLQ: $DLQ_NAME"
if aws sqs get-queue-url --queue-name "$DLQ_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "  ✓ DLQ $DLQ_NAME exists"
else
  aws sqs create-queue --queue-name "$DLQ_NAME" \
    --attributes '{"VisibilityTimeout":"30","MessageRetentionPeriod":"1209600"}' \
    --region "$REGION" >/dev/null
  echo "  ✓ DLQ $DLQ_NAME created"
fi
DLQ_URL=$(aws sqs get-queue-url --queue-name "$DLQ_NAME" --region "$REGION" \
  --query QueueUrl --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url "$DLQ_URL" \
  --attribute-names QueueArn --region "$REGION" \
  --query 'Attributes.QueueArn' --output text)

# ── 2. Extend stream role policy with new permissions ────────────────────
echo ""
echo "[2/6] Extending stream-role policy (states:StartExecution, bedrock:InvokeModel, sqs:SendMessage)"

EXTRA_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "StateMachineInvoke",
      "Effect": "Allow",
      "Action": ["states:StartExecution", "states:DescribeExecution"],
      "Resource": "arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:inference-pipeline-${LEARNER}"
    },
    {
      "Sid": "BedrockInvoke",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "*"
    },
    {
      "Sid": "CWGetMetrics",
      "Effect": "Allow",
      "Action": ["cloudwatch:GetMetricStatistics"],
      "Resource": "*"
    },
    {
      "Sid": "DDBUpdate",
      "Effect": "Allow",
      "Action": ["dynamodb:UpdateItem"],
      "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${IDEMP_TABLE}"
    },
    {
      "Sid": "S3EnrichedWrite",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::${BUCKET}/enriched/${LEARNER}/*"
    },
    {
      "Sid": "DLQSend",
      "Effect": "Allow",
      "Action": ["sqs:SendMessage"],
      "Resource": "${DLQ_ARN}"
    }
  ]
}
EOF
)
echo "$EXTRA_POLICY" > /tmp/m8-extra-policy.json
aws iam put-role-policy \
  --role-name "$STREAM_ROLE" \
  --policy-name "M8ExtraPolicy" \
  --policy-document "file:///tmp/m8-extra-policy.json"
echo "  ✓ M8ExtraPolicy attached"
sleep 5  # IAM propagation

# ── 3-6. Deploy 4 Lambdas ────────────────────────────────────────────────
build_zip() {
  local SUBDIR="$1" ZIP_NAME="$2"
  rm -rf "$BUILD_DIR"
  mkdir -p "$BUILD_DIR/common"
  cp "$STARTER_REPO/src/$SUBDIR/handler.py" "$BUILD_DIR/handler.py"
  cp "$STARTER_REPO/src/common/__init__.py" "$BUILD_DIR/common/__init__.py"
  cp "$STARTER_REPO/src/common/exceptions.py" "$BUILD_DIR/common/exceptions.py"
  ( cd "$BUILD_DIR" && zip -qr "$ZIP_DIR/$ZIP_NAME" . )
}

deploy_lambda() {
  # deploy_lambda <fn_name> <zip> <handler> <memory> <timeout> <env>
  local NAME="$1" ZIP="$2" HANDLER="$3" MEM="$4" TIMEOUT="$5" ENV="$6"
  if aws lambda get-function --function-name "$NAME" --region "$REGION" >/dev/null 2>&1; then
    echo "  ✓ $NAME exists; updating code + config..."
    aws lambda update-function-code \
      --function-name "$NAME" --zip-file "fileb://$ZIP" --region "$REGION" >/dev/null
    aws lambda wait function-updated-v2 --function-name "$NAME" --region "$REGION"
    aws lambda update-function-configuration \
      --function-name "$NAME" \
      --memory-size "$MEM" --timeout "$TIMEOUT" \
      --environment "$ENV" --region "$REGION" >/dev/null
    aws lambda wait function-updated-v2 --function-name "$NAME" --region "$REGION"
  else
    echo "  → creating $NAME..."
    aws lambda create-function \
      --function-name "$NAME" \
      --runtime python3.12 \
      --architectures x86_64 \
      --handler handler.handler \
      --role "$STREAM_ROLE_ARN" \
      --memory-size "$MEM" --timeout "$TIMEOUT" \
      --environment "$ENV" \
      --zip-file "fileb://$ZIP" \
      --tags programme=accelya-agentic-aws,module=m8 \
      --region "$REGION" >/dev/null
    aws lambda wait function-active-v2 --function-name "$NAME" --region "$REGION"
  fi
}

mkdir -p "$ZIP_DIR"

echo ""
echo "[3/6] Lambda: $PRODUCER_FN"
build_zip "producer" "producer.zip"
deploy_lambda "$PRODUCER_FN" "$ZIP_DIR/producer.zip" "handler.handler" 512 60 \
  "Variables={STREAM_NAME=$STREAM,LEARNER=$LEARNER}"

echo ""
echo "[4/6] Lambda: $ENRICH_FN"
build_zip "bedrock_enrich" "enrich.zip"
deploy_lambda "$ENRICH_FN" "$ZIP_DIR/enrich.zip" "handler.handler" 1024 60 \
  "Variables={SAMPLE_RATE=10,BEDROCK_MAX_INVOCATIONS=38,BEDROCK_MAX_TOKENS=18000,MODEL_ID=apac.anthropic.claude-3-5-sonnet-20241022-v2:0,LEARNER=$LEARNER}"

echo ""
echo "[5/6] Lambda: $PERSIST_FN"
build_zip "persist_enriched" "persist.zip"
deploy_lambda "$PERSIST_FN" "$ZIP_DIR/persist.zip" "handler.handler" 512 30 \
  "Variables={BUCKET_NAME=$BUCKET,LEARNER=$LEARNER}"

# Consumer needs SM_ARN — but we don't have it yet. Deploy with placeholder;
# update via scripts/deploy_m8_state_machine.sh.
echo ""
echo "[6/6] Lambda: $CONSUMER_FN (SM_ARN will be set by state-machine deploy)"
build_zip "consumer" "consumer.zip"
SM_ARN_PLACEHOLDER="arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:inference-pipeline-${LEARNER}"
deploy_lambda "$CONSUMER_FN" "$ZIP_DIR/consumer.zip" "handler.handler" 512 60 \
  "Variables={STREAM_NAME=$STREAM,LEARNER=$LEARNER,IDEMP_TABLE=$IDEMP_TABLE,SM_ARN=$SM_ARN_PLACEHOLDER,QUARANTINE_BUCKET=$BUCKET}"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ 4 Lambdas + DLQ deployed"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Captured values for next step:"
echo "  STREAM_ARN=$STREAM_ARN"
echo "  STREAM_ROLE_ARN=$STREAM_ROLE_ARN"
echo "  DLQ_ARN=$DLQ_ARN"
echo ""
echo "Next steps:"
echo "  1. Deploy the state machine:"
echo "       bash scripts/deploy_m8_state_machine.sh $LEARNER"
echo ""
echo "  2. Wire the ESM (Lab 2 step 1):"
echo "       aws lambda create-event-source-mapping \\"
echo "         --function-name $CONSUMER_FN \\"
echo "         --event-source-arn $STREAM_ARN \\"
echo "         --batch-size 100 \\"
echo "         --maximum-batching-window-in-seconds 5 \\"
echo "         --parallelization-factor 1 \\"
echo "         --maximum-retry-attempts 3 \\"
echo "         --maximum-record-age-in-seconds 3600 \\"
echo "         --bisect-batch-on-function-error \\"
echo "         --function-response-types ReportBatchItemFailures \\"
echo "         --starting-position LATEST \\"
echo "         --destination-config '{\"OnFailure\":{\"Destination\":\"$DLQ_ARN\"}}' \\"
echo "         --region $REGION"
