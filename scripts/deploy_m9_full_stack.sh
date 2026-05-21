#!/usr/bin/env bash
# Day 9 — single-paste full stack deploy for LEARNERS.
#
# Mirrors trainer-deliverables/46_create_m9_pipeline.sh but is checked into the
# starter repo so every learner can run it with their own <learner> argument.
#
# What this does:
#   1. Verifies Day-7 + Day-8 prereqs are alive (else points to fix scripts)
#   2. Ensures the shared model artefact exists in S3 (builds + uploads if missing)
#   3. Deploys SageMaker model + config + endpoint (waits for InService)
#   4. Builds + deploys wrapper Lambda accelya-predict-cancel-risk-<learner>
#   5. Extends Day-7 stream role with sagemaker:InvokeEndpoint + S3 review write
#   6. Creates SQS model-review-queue-<learner>
#   7. Extends Day-5 SFN role with invoke wrapper + SQS sendMessage + S3 write
#   8. Renders + validates + updates inference-pipeline-<learner> ASL
#   9. Direct invokes wrapper Lambda to confirm risk_score + confidence returned
#
# Sandbox notes:
#   - Only ONE SageMaker endpoint allowed per AWS account at a time
#   - Coordinate with other learners — only one person deploys at a time
#   - Endpoint MUST be deleted at end of Lab 3 (reset_module9_endpoint.sh <learner>)
#
# Usage (replace <your-name>):
#   bash scripts/deploy_m9_full_stack.sh <your-name>
#
# Idempotent — re-run safely if anything trips midway.

set -uo pipefail   # intentionally NOT -e — surface ALL failures, don't abort silently

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <your-name>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
BUCKET="${BUCKET_NAME:-accelya-airline-data-ap-south-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)

ENDPOINT_NAME="accelya-cancel-risk-${LEARNER}"
WRAPPER_FN="accelya-predict-cancel-risk-${LEARNER}"
REVIEW_QUEUE="model-review-queue-${LEARNER}"
SM_NAME="inference-pipeline-${LEARNER}"
STREAM_ROLE="accelya-stream-role-${LEARNER}"
SFN_ROLE_NAME="${SFN_ROLE_NAME:-accelya-m5-sfn-${LEARNER}-role}"
MODEL_ARTEFACT="s3://${BUCKET}/models/cancel-risk/v1.2.3/model.tar.gz"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
STARTER_REPO="$( cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
ASL_TEMPLATE="$STARTER_REPO/infra/inference-pipeline.asl.json"
ASL_RENDERED="/tmp/inference-pipeline-${LEARNER}-d9.rendered.asl.json"

say() { printf '%s\n' "$*"; }
hdr() { printf '\n─── %s ───\n' "$*"; }

say "═══════════════════════════════════════════════════════════════"
say " Day 9 — full stack deploy"
say " Region:    $REGION"
say " Bucket:    s3://$BUCKET"
say " Learner:   $LEARNER"
say " Endpoint:  $ENDPOINT_NAME"
say " Wrapper:   $WRAPPER_FN"
say " Review Q:  $REVIEW_QUEUE"
say " StateMch:  $SM_NAME"
say "═══════════════════════════════════════════════════════════════"

# ── 1. Pre-flight ─────────────────────────────────────────────────────────
hdr "1. Pre-flight checks"

for CMD in aws python3 jq zip envsubst; do
  if ! command -v "$CMD" >/dev/null 2>&1; then
    say "❌ Required command missing: $CMD"
    exit 1
  fi
done

if [[ -z "$ACCOUNT_ID" ]]; then
  say "❌ AWS creds not set. Run: aws configure"
  exit 1
fi
say "  ✓ AWS account: $ACCOUNT_ID"

# Day-7 prereqs
if ! aws iam get-role --role-name "$STREAM_ROLE" >/dev/null 2>&1; then
  say "❌ Day-7 stream role missing: $STREAM_ROLE"
  say "   Run: bash scripts/provision_m7_stream.sh $LEARNER"
  exit 1
fi
say "  ✓ Day-7 stream role present"

if ! aws iam get-role --role-name "$SFN_ROLE_NAME" >/dev/null 2>&1; then
  say "❌ Day-5 SFN role missing: $SFN_ROLE_NAME"
  say "   Run: bash scripts/provision_m5_resources.sh $LEARNER"
  exit 1
fi
say "  ✓ Day-5 SFN role present"

# Day-8 prereqs
for FN in accelya-producer-${LEARNER} accelya-consumer-${LEARNER} \
          accelya-bedrock-enrich-${LEARNER} accelya-persist-enriched-${LEARNER}; do
  if ! aws lambda get-function --function-name "$FN" --region "$REGION" >/dev/null 2>&1; then
    say "❌ Day-8 Lambda missing: $FN"
    say "   Run: bash scripts/deploy_m8_lambdas.sh $LEARNER"
    exit 1
  fi
done
say "  ✓ Day-8 Lambdas Active (4 of 4)"

if ! aws stepfunctions list-state-machines --region "$REGION" \
     --query "stateMachines[?name=='$SM_NAME']" --output text | grep -q "$SM_NAME"; then
  say "❌ Day-8 state machine missing: $SM_NAME"
  say "   Run: bash scripts/deploy_m8_state_machine.sh $LEARNER"
  exit 1
fi
say "  ✓ Day-8 state machine present"

# Sandbox cap check — fail-fast if another endpoint is hogging the slot
OTHER_EP=$(aws sagemaker list-endpoints --region "$REGION" \
  --query "Endpoints[?EndpointName != '$ENDPOINT_NAME' && contains(EndpointName,'cancel-risk')].EndpointName" \
  --output text 2>/dev/null)
if [[ -n "$OTHER_EP" ]]; then
  say "❌ Another SageMaker endpoint exists (sandbox cap = 1 per account):"
  say "     $OTHER_EP"
  say "   Coordinate with that learner — only one endpoint at a time."
  say "   Or, if it's stale, delete: aws sagemaker delete-endpoint --endpoint-name <name> --region $REGION"
  exit 1
fi
say "  ✓ Sandbox endpoint slot free"

# ── 2. Ensure model artefact exists in S3 ────────────────────────────────
hdr "2. Model artefact in S3"

if aws s3 ls "$MODEL_ARTEFACT" --region "$REGION" >/dev/null 2>&1; then
  say "  ✓ Model artefact already at $MODEL_ARTEFACT"
  say "    (Shared across cohort — built once by the trainer or first learner)"
else
  say "  → Model artefact missing; building..."
  say "    This trains a stub model + uploads ~3 KB tarball (~30 s)"
  bash "$SCRIPT_DIR/build_m9_model_artefact.sh" 2>&1 | sed 's/^/    /'

  if ! aws s3 ls "$MODEL_ARTEFACT" --region "$REGION" >/dev/null 2>&1; then
    say "  ❌ Model artefact build failed"
    exit 1
  fi
  say "  ✓ Model artefact built + uploaded"
fi

# ── 3. Deploy SageMaker endpoint ──────────────────────────────────────────
hdr "3. SageMaker model + config + endpoint"

bash "$SCRIPT_DIR/deploy_m9_endpoint.sh" "$LEARNER" 2>&1 | sed 's/^/    /'

# Verify endpoint InService
STATUS=$(aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" \
  --region "$REGION" --query 'EndpointStatus' --output text 2>/dev/null)
if [[ "$STATUS" != "InService" ]]; then
  say ""
  say "❌ Endpoint not InService (status=$STATUS)"
  say "   Inspect: aws sagemaker describe-endpoint --endpoint-name $ENDPOINT_NAME --region $REGION"
  exit 1
fi
say "  ✓ Endpoint InService"

# ── 4. Build + deploy wrapper Lambda ─────────────────────────────────────
hdr "4. Wrapper Lambda: $WRAPPER_FN"

STREAM_ROLE_ARN=$(aws iam get-role --role-name "$STREAM_ROLE" --query 'Role.Arn' --output text)

BUILD_DIR="/tmp/m9-wrapper-build"
ZIP_PATH="/tmp/m9-predict.zip"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/common"
cp "$STARTER_REPO/src/predict/handler.py" "$BUILD_DIR/handler.py"
cp "$STARTER_REPO/src/common/__init__.py" "$BUILD_DIR/common/__init__.py"
cp "$STARTER_REPO/src/common/exceptions.py" "$BUILD_DIR/common/exceptions.py"
( cd "$BUILD_DIR" && zip -qr "$ZIP_PATH" . )
say "  ✓ Zip built: $(du -h $ZIP_PATH | cut -f1)"

WRAPPER_ENV="Variables={ENDPOINT_NAME=$ENDPOINT_NAME,CONFIDENCE_THRESHOLD=0.7}"

if aws lambda get-function --function-name "$WRAPPER_FN" --region "$REGION" >/dev/null 2>&1; then
  say "  → wrapper exists; updating code + config..."
  aws lambda update-function-code \
    --function-name "$WRAPPER_FN" --zip-file "fileb://$ZIP_PATH" --region "$REGION" >/dev/null
  aws lambda wait function-updated-v2 --function-name "$WRAPPER_FN" --region "$REGION"
  aws lambda update-function-configuration \
    --function-name "$WRAPPER_FN" \
    --memory-size 512 --timeout 45 \
    --environment "$WRAPPER_ENV" \
    --region "$REGION" >/dev/null
  aws lambda wait function-updated-v2 --function-name "$WRAPPER_FN" --region "$REGION"
else
  say "  → creating $WRAPPER_FN..."
  aws lambda create-function \
    --function-name "$WRAPPER_FN" \
    --runtime python3.12 --architectures x86_64 \
    --handler handler.handler \
    --role "$STREAM_ROLE_ARN" \
    --memory-size 512 --timeout 45 \
    --environment "$WRAPPER_ENV" \
    --zip-file "fileb://$ZIP_PATH" \
    --tags programme=accelya-agentic-aws,module=m9,learner=$LEARNER \
    --region "$REGION" >/dev/null
  aws lambda wait function-active-v2 --function-name "$WRAPPER_FN" --region "$REGION"
fi
say "  ✓ $WRAPPER_FN deployed (memory=512, timeout=45)"

# ── 5. Extend stream role + create review queue + extend SFN role ────────
hdr "5. IAM extensions + SQS review queue"

# 5a. Stream role: sagemaker:InvokeEndpoint + S3 review/ write
M9_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeSageMakerEndpoint",
      "Effect": "Allow",
      "Action": ["sagemaker:InvokeEndpoint"],
      "Resource": "arn:aws:sagemaker:${REGION}:${ACCOUNT_ID}:endpoint/${ENDPOINT_NAME}"
    },
    {
      "Sid": "S3ReviewWrite",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::${BUCKET}/review/${LEARNER}/*"
    }
  ]
}
EOF
)
echo "$M9_POLICY" > /tmp/m9-policy.json
aws iam put-role-policy \
  --role-name "$STREAM_ROLE" \
  --policy-name "M9InvokeEndpointPolicy" \
  --policy-document "file:///tmp/m9-policy.json"
say "  ✓ Stream role: M9InvokeEndpointPolicy attached"

# 5b. SQS review queue
if aws sqs get-queue-url --queue-name "$REVIEW_QUEUE" --region "$REGION" >/dev/null 2>&1; then
  say "  ✓ Queue $REVIEW_QUEUE exists"
else
  aws sqs create-queue --queue-name "$REVIEW_QUEUE" \
    --attributes '{"VisibilityTimeout":"60","MessageRetentionPeriod":"1209600"}' \
    --region "$REGION" >/dev/null
  say "  ✓ Queue $REVIEW_QUEUE created"
fi
REVIEW_QUEUE_URL=$(aws sqs get-queue-url --queue-name "$REVIEW_QUEUE" --region "$REGION" \
  --query QueueUrl --output text)
REVIEW_QUEUE_ARN=$(aws sqs get-queue-attributes --queue-url "$REVIEW_QUEUE_URL" \
  --attribute-names QueueArn --region "$REGION" \
  --query 'Attributes.QueueArn' --output text)

# 5c. SFN role: invoke wrapper + sqs:SendMessage + s3:PutObject
SFN_M9_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeM9Wrapper",
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${WRAPPER_FN}"
    },
    {
      "Sid": "SfnSqsSendReview",
      "Effect": "Allow",
      "Action": ["sqs:SendMessage"],
      "Resource": "${REVIEW_QUEUE_ARN}"
    },
    {
      "Sid": "SfnS3WriteReview",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::${BUCKET}/review/${LEARNER}/*"
    }
  ]
}
EOF
)
echo "$SFN_M9_POLICY" > /tmp/m9-sfn-policy.json
aws iam put-role-policy --role-name "$SFN_ROLE_NAME" \
  --policy-name "M9SfnInvokeAndSinkPolicy" \
  --policy-document "file:///tmp/m9-sfn-policy.json"
say "  ✓ SFN role: M9SfnInvokeAndSinkPolicy attached"

sleep 5  # IAM propagation

# ── 6. Render + validate + update ASL ────────────────────────────────────
hdr "6. Update state machine with Parallel + Choice"

export AWS_REGION="$REGION"
export AWS_ACCOUNT_ID="$ACCOUNT_ID"
export LEARNER
export BUCKET_NAME="$BUCKET"
export MODEL_REVIEW_QUEUE_URL="$REVIEW_QUEUE_URL"

envsubst < "$ASL_TEMPLATE" > "$ASL_RENDERED"

VAL=$(aws stepfunctions validate-state-machine-definition \
  --region "$REGION" \
  --definition "file://$ASL_RENDERED" \
  --query 'result' --output text)
if [[ "$VAL" != "OK" ]]; then
  say "  ❌ ASL validation failed:"
  aws stepfunctions validate-state-machine-definition \
    --region "$REGION" \
    --definition "file://$ASL_RENDERED" \
    --query 'diagnostics' --output json | sed 's/^/    /'
  exit 1
fi
say "  ✓ ASL validates"

SM_ARN=$(aws stepfunctions list-state-machines --region "$REGION" \
  --query "stateMachines[?name=='$SM_NAME'].stateMachineArn" --output text)

aws stepfunctions update-state-machine \
  --state-machine-arn "$SM_ARN" \
  --definition "file://$ASL_RENDERED" \
  --region "$REGION" >/dev/null
say "  ✓ State machine updated (Parallel + Choice + Review sinks)"

# ── 7. Smoke-test wrapper Lambda ─────────────────────────────────────────
hdr "7. Smoke-test wrapper Lambda"

SMOKE_PAYLOAD='{"booking_id":"BK-SMOKE-001","fare_amount":4500.00,"refund_lag_hours":0.5,"prior_cancels":0,"event_id":"smoke-'${LEARNER}'-001","corr_id":"smoke"}'

aws lambda invoke \
  --function-name "$WRAPPER_FN" \
  --cli-binary-format raw-in-base64-out \
  --payload "$SMOKE_PAYLOAD" \
  --region "$REGION" \
  /tmp/m9-smoke-out.json >/dev/null

say "  Wrapper response:"
cat /tmp/m9-smoke-out.json | python3 -m json.tool 2>/dev/null | sed 's/^/    /' \
  || cat /tmp/m9-smoke-out.json

HAS_RISK=$(jq -r 'has("risk_score")' /tmp/m9-smoke-out.json 2>/dev/null || echo "false")
HAS_CONF=$(jq -r 'has("confidence")' /tmp/m9-smoke-out.json 2>/dev/null || echo "false")
HAS_ERR=$(jq -r 'has("errorMessage")' /tmp/m9-smoke-out.json 2>/dev/null || echo "false")

# ── Summary ───────────────────────────────────────────────────────────────
say ""
say "═══════════════════════════════════════════════════════════════"
if [[ "$HAS_RISK" == "true" && "$HAS_CONF" == "true" && "$HAS_ERR" == "false" ]]; then
  say " ✅ Day 9 full stack LIVE"
else
  say " ⚠️  Day 9 deployed but smoke test failed — investigate logs:"
  say "    aws logs tail /aws/sagemaker/Endpoints/$ENDPOINT_NAME --region $REGION --since 5m"
  say "    aws logs tail /aws/lambda/$WRAPPER_FN --region $REGION --since 5m"
fi
say "═══════════════════════════════════════════════════════════════"
say ""
say "Resources deployed:"
say "  Endpoint:    $ENDPOINT_NAME"
say "  Wrapper:     $WRAPPER_FN  (Lambda count now 10 of 10 FINAL CAP)"
say "  Review Q:    $REVIEW_QUEUE_URL"
say "  StateMch:    $SM_ARN  (Parallel + Choice + Review sinks)"
say ""
say "Next — Lab 3 routing demo:"
say "  python3 -m scripts.gen_m9_test_batch --high-conf 7 --low-conf 3 --out /tmp/m9-10.json"
say "  aws lambda invoke --function-name accelya-producer-$LEARNER \\"
say "    --cli-binary-format raw-in-base64-out --payload file:///tmp/m9-10.json \\"
say "    --region $REGION /tmp/out.json"
say ""
say "⚠️  CRITICAL — DELETE ENDPOINT AT END OF LAB 3 (sandbox cap = 1):"
say "  bash scripts/reset_module9_endpoint.sh $LEARNER"
