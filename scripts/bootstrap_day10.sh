#!/usr/bin/env bash
# bootstrap_day10.sh — daily-reset bootstrap for Day 10 labs.
#
# WHY: Pluralsight sandbox resets every night. Every learner needs to recreate
# all 10 Lambdas + state machine + Kinesis + DDB + SQS + IAM + SageMaker
# endpoint + observability stack each morning before Day 10 labs.
#
# WHAT THIS DOES (~8-12 min cold; ~2 min on re-run):
#   STAGE 1 — Identity & prereqs
#   STAGE 2 — Shared S3 prefixes
#   STAGE 3 — IAM role accelya-stream-role-<learner>
#   STAGE 4 — Kinesis stream cancellation-events-<learner> (2 shards)
#   STAGE 5 — DynamoDB stream_seen_keys_<learner> (idempotency)
#   STAGE 6 — SQS stream-dlq-<learner>
#   STAGE 7 — Lambdas 1-7 (everything except Day-8 enrich/persist + Day-9 predict)
#   STAGE 8 — Day-8 streaming Lambdas (producer/consumer/bedrock_enrich/persist_enriched)
#   STAGE 9 — Step Functions state machine inference-pipeline-<learner>
#   STAGE 10 — Day-8 ESM (Kinesis → consumer Lambda)
#   STAGE 11 — Day-9 SageMaker endpoint (optional; --skip-endpoint to skip)
#   STAGE 12 — Day-9 predict wrapper Lambda + ASL Parallel extension
#   STAGE 13 — Day-10 observability (powertools libs ready + log retention + TracingConfig)
#
# USAGE:
#   bash scripts/bootstrap_day10.sh <learner>                 # full bootstrap
#   bash scripts/bootstrap_day10.sh <learner> --skip-endpoint # skip SageMaker (if cap hit)
#   bash scripts/bootstrap_day10.sh <learner> --verify-only   # just check what's missing
#   bash scripts/bootstrap_day10.sh <learner> --teardown      # nuke everything you own
#
# DESIGN PRINCIPLES:
# 1. EVERY step is idempotent — safe to re-run after any failure
# 2. EVERY step prints PASS/FAIL with the exact resolution hint
# 3. NO hard-coded account IDs / queue URLs — resolved at runtime via sts/sqs
# 4. Tolerates sandbox quirks we learned the hard way:
#    - 1-DIMENSIONAL-monitor cap (reuse Default-Services-Monitor)
#    - put-metric-alarm rejects Offset (use ANOMALY_DETECTION_BAND)
#    - dashboard metric tuples max 4 items
#    - Cost Anomaly subscription needs IMMEDIATE frequency for SNS
#    - IAM eventual consistency (15s sleep after policy create)
#    - 5-version IAM policy cap (prune oldest before create)
# 5. Bedrock budget aware — exits at 38 invocations / 18K tokens (lab cap)
# 6. Cascade-friendly — verification commands printed verbatim for self-debug

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Args + config
# ──────────────────────────────────────────────────────────────────────────
LEARNER="${1:-}"
MODE="full"
[[ "${2:-}" == "--skip-endpoint" ]] && MODE="skip-endpoint"
[[ "${2:-}" == "--verify-only"  ]] && MODE="verify-only"
[[ "${2:-}" == "--teardown"     ]] && MODE="teardown"

if [[ -z "$LEARNER" ]]; then
  echo "Usage: bash scripts/bootstrap_day10.sh <learner> [--skip-endpoint|--verify-only|--teardown]"
  echo ""
  echo "  <learner>          your name suffix (e.g. 'jai', 'priya'); lowercase, no spaces"
  echo "  --skip-endpoint    skip SageMaker endpoint (if another learner has the cap)"
  echo "  --verify-only      check what's present without creating anything"
  echo "  --teardown         delete everything tagged with your learner suffix"
  exit 1
fi

# Sanity: lowercase, alphanumeric only
if ! [[ "$LEARNER" =~ ^[a-z][a-z0-9-]*$ ]]; then
  echo "❌ Learner name must be lowercase letters/digits/hyphens, starting with a letter."
  exit 1
fi

export AWS_REGION="${AWS_REGION:-ap-south-1}"
COST_REGION="us-east-1"   # AWS Cost Explorer is global → us-east-1
BUCKET="${SHARED_BUCKET:-accelya-airline-data-ap-south-1}"

# Repo layout
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
SRC_DIR="$REPO_ROOT/src"
INFRA_DIR="$REPO_ROOT/infra"

# ──────────────────────────────────────────────────────────────────────────
# Visual + helpers
# ──────────────────────────────────────────────────────────────────────────
COL_GREEN='\033[0;32m'; COL_YELLOW='\033[0;33m'; COL_RED='\033[0;31m'; COL_BLUE='\033[0;34m'; COL_OFF='\033[0m'

stage() { printf "\n${COL_BLUE}━━━ STAGE %s ━━━${COL_OFF} %s\n" "$1" "$2"; }
ok()    { printf "  ${COL_GREEN}✓${COL_OFF} %s\n" "$1"; }
warn()  { printf "  ${COL_YELLOW}⚠${COL_OFF} %s\n" "$1"; }
err()   { printf "  ${COL_RED}✗${COL_OFF} %s\n" "$1"; }
hint()  { printf "      ${COL_YELLOW}→${COL_OFF} %s\n" "$1"; }

require() { command -v "$1" >/dev/null 2>&1 || { err "Missing CLI: $1"; exit 1; }; }

# ──────────────────────────────────────────────────────────────────────────
# STAGE 1 — Identity & prereqs
# ──────────────────────────────────────────────────────────────────────────
stage 1 "Identity & prereqs"

require aws; require jq; require python3; require zip
if ! aws sts get-caller-identity --region "$AWS_REGION" >/dev/null 2>&1; then
  err "AWS credentials not set or invalid for region $AWS_REGION"
  hint "Open a fresh sandbox tab and re-run after creds are in place."
  exit 1
fi
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ok "Account ID: $ACCOUNT_ID   Region: $AWS_REGION   Learner: $LEARNER"

# Single names (used everywhere downstream)
ROLE_NAME="accelya-stream-role-${LEARNER}"
STREAM_NAME="cancellation-events-${LEARNER}"
DDB_TABLE="stream_seen_keys_${LEARNER}"
DLQ_NAME="stream-dlq-${LEARNER}"
REVIEW_QUEUE="model-review-queue-${LEARNER}"
SM_NAME="inference-pipeline-${LEARNER}"
SM_ARN="arn:aws:states:${AWS_REGION}:${ACCOUNT_ID}:stateMachine:${SM_NAME}"
ENDPOINT_NAME="accelya-cancel-risk-${LEARNER}"

LAMBDAS_ALL=(
  "accelya-validator-${LEARNER}"
  "accelya-lander-${LEARNER}"
  "accelya-chunker-${LEARNER}"
  "accelya-dlq-replayer-${LEARNER}"
  "accelya-etl-json-to-parquet-${LEARNER}"
  "accelya-producer-${LEARNER}"
  "accelya-consumer-${LEARNER}"
  "accelya-bedrock-enrich-${LEARNER}"
  "accelya-persist-enriched-${LEARNER}"
  "accelya-predict-cancel-risk-${LEARNER}"
)

# ──────────────────────────────────────────────────────────────────────────
# TEARDOWN mode
# ──────────────────────────────────────────────────────────────────────────
if [[ "$MODE" == "teardown" ]]; then
  stage T "Teardown — delete everything tagged $LEARNER"
  for FN in "${LAMBDAS_ALL[@]}"; do
    aws lambda delete-function --function-name "$FN" --region "$AWS_REGION" 2>/dev/null \
      && ok "Lambda $FN" || warn "Lambda $FN not present"
  done
  aws stepfunctions delete-state-machine --state-machine-arn "$SM_ARN" \
    --region "$AWS_REGION" 2>/dev/null && ok "State machine $SM_NAME" || warn "State machine missing"
  aws kinesis delete-stream --stream-name "$STREAM_NAME" --enforce-consumer-deletion \
    --region "$AWS_REGION" 2>/dev/null && ok "Kinesis $STREAM_NAME" || warn "Stream missing"
  aws dynamodb delete-table --table-name "$DDB_TABLE" --region "$AWS_REGION" 2>/dev/null \
    && ok "DDB $DDB_TABLE" || warn "Table missing"
  DLQ_URL=$(aws sqs get-queue-url --queue-name "$DLQ_NAME" --region "$AWS_REGION" \
    --query QueueUrl --output text 2>/dev/null || echo "")
  [[ -n "$DLQ_URL" && "$DLQ_URL" != "None" ]] \
    && aws sqs delete-queue --queue-url "$DLQ_URL" --region "$AWS_REGION" \
    && ok "SQS $DLQ_NAME" || warn "DLQ missing"
  REVIEW_URL=$(aws sqs get-queue-url --queue-name "$REVIEW_QUEUE" --region "$AWS_REGION" \
    --query QueueUrl --output text 2>/dev/null || echo "")
  [[ -n "$REVIEW_URL" && "$REVIEW_URL" != "None" ]] \
    && aws sqs delete-queue --queue-url "$REVIEW_URL" --region "$AWS_REGION" \
    && ok "SQS $REVIEW_QUEUE" || warn "Review queue missing"
  EP_NAME=$(aws sagemaker list-endpoints --region "$AWS_REGION" \
    --query "Endpoints[?contains(EndpointName,'$LEARNER')].EndpointName | [0]" \
    --output text 2>/dev/null || echo "")
  [[ -n "$EP_NAME" && "$EP_NAME" != "None" ]] \
    && aws sagemaker delete-endpoint --endpoint-name "$EP_NAME" --region "$AWS_REGION" \
    && ok "SageMaker endpoint $EP_NAME" || warn "Endpoint missing"
  aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "${ROLE_NAME}-policy" 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE_NAME" 2>/dev/null \
    && ok "IAM role $ROLE_NAME" || warn "Role missing"
  ok "Teardown complete. Sandbox quota freed."
  exit 0
fi

# ──────────────────────────────────────────────────────────────────────────
# VERIFY-ONLY mode (skip to summary at end)
# ──────────────────────────────────────────────────────────────────────────
if [[ "$MODE" == "verify-only" ]]; then
  stage V "Verify-only — what's currently present"
fi

# ──────────────────────────────────────────────────────────────────────────
# STAGE 2 — Shared S3 prefixes (idempotent)
# ──────────────────────────────────────────────────────────────────────────
stage 2 "S3 prefixes under shared bucket $BUCKET"

if ! aws s3api head-bucket --bucket "$BUCKET" --region "$AWS_REGION" 2>/dev/null; then
  err "Bucket s3://$BUCKET missing. Trainer hasn't bootstrapped shared resources."
  hint "Ask trainer to run 12_bootstrap_shared_aws_resources.sh in their account."
  exit 1
fi
ok "Shared bucket exists"

if [[ "$MODE" != "verify-only" ]]; then
  for PREFIX in raw curated review enriched quarantine athena-results; do
    aws s3api put-object --bucket "$BUCKET" --key "$PREFIX/$LEARNER/" \
      --region "$AWS_REGION" >/dev/null 2>&1 || true
  done
  ok "S3 prefixes ready under $LEARNER/"
fi

# ──────────────────────────────────────────────────────────────────────────
# STAGE 3 — IAM role
# ──────────────────────────────────────────────────────────────────────────
stage 3 "IAM role $ROLE_NAME"

ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" \
  --query 'Role.Arn' --output text 2>/dev/null || echo "")

if [[ -z "$ROLE_ARN" || "$ROLE_ARN" == "None" ]]; then
  if [[ "$MODE" == "verify-only" ]]; then
    err "Role missing"
  else
    cat > /tmp/${LEARNER}-trust.json <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":["lambda.amazonaws.com","states.amazonaws.com"]},
 "Action":"sts:AssumeRole"}]}
JSON
    ROLE_ARN=$(aws iam create-role --role-name "$ROLE_NAME" \
      --assume-role-policy-document file:///tmp/${LEARNER}-trust.json \
      --tags "Key=programme,Value=accelya" "Key=owner,Value=$LEARNER" "Key=environment,Value=lab" \
      --query 'Role.Arn' --output text)
    ok "Created $ROLE_ARN"
    aws iam attach-role-policy --role-name "$ROLE_NAME" \
      --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true
    aws iam attach-role-policy --role-name "$ROLE_NAME" \
      --policy-arn arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess 2>/dev/null || true
    sleep 8   # IAM eventual consistency
  fi
else
  ok "Role exists: $ROLE_ARN"
fi

# Inline policy — broad-but-scoped (we tighten in Day-10 Lab 3)
if [[ "$MODE" != "verify-only" && -n "$ROLE_ARN" ]]; then
  cat > /tmp/${LEARNER}-inline.json <<JSON
{
  "Version":"2012-10-17",
  "Statement":[
    {"Sid":"S3Data","Effect":"Allow",
     "Action":["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
     "Resource":["arn:aws:s3:::$BUCKET","arn:aws:s3:::$BUCKET/*"]},
    {"Sid":"DDB","Effect":"Allow","Action":"dynamodb:*",
     "Resource":"arn:aws:dynamodb:$AWS_REGION:$ACCOUNT_ID:table/${DDB_TABLE}"},
    {"Sid":"Bedrock","Effect":"Allow","Action":"bedrock:InvokeModel","Resource":"*"},
    {"Sid":"SageMakerInvoke","Effect":"Allow","Action":"sagemaker:InvokeEndpoint",
     "Resource":"arn:aws:sagemaker:$AWS_REGION:$ACCOUNT_ID:endpoint/${ENDPOINT_NAME}"},
    {"Sid":"Kinesis","Effect":"Allow","Action":"kinesis:*",
     "Resource":"arn:aws:kinesis:$AWS_REGION:$ACCOUNT_ID:stream/${STREAM_NAME}"},
    {"Sid":"SQS","Effect":"Allow","Action":"sqs:*","Resource":"*"},
    {"Sid":"SFN","Effect":"Allow","Action":"states:StartExecution",
     "Resource":"$SM_ARN"},
    {"Sid":"SNSPub","Effect":"Allow","Action":"sns:Publish","Resource":"*"},
    {"Sid":"SageMakerExec","Effect":"Allow",
     "Action":["sagemaker:CreateModel","sagemaker:CreateEndpointConfig",
               "sagemaker:CreateEndpoint","sagemaker:DescribeEndpoint",
               "sagemaker:DeleteEndpoint","sagemaker:DeleteEndpointConfig",
               "sagemaker:DeleteModel","iam:PassRole"],
     "Resource":"*"},
    {"Sid":"Logs","Effect":"Allow",
     "Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents",
               "logs:DescribeLogGroups","logs:PutRetentionPolicy"],
     "Resource":"*"},
    {"Sid":"XRay","Effect":"Allow",
     "Action":["xray:PutTraceSegments","xray:PutTelemetryRecords",
               "xray:GetSamplingRules","xray:GetSamplingTargets"],
     "Resource":"*"}
  ]
}
JSON
  aws iam put-role-policy --role-name "$ROLE_NAME" \
    --policy-name "${ROLE_NAME}-policy" \
    --policy-document file:///tmp/${LEARNER}-inline.json
  ok "Inline policy attached"
fi

# ──────────────────────────────────────────────────────────────────────────
# STAGE 4 — Kinesis stream
# ──────────────────────────────────────────────────────────────────────────
stage 4 "Kinesis stream $STREAM_NAME (2 shards)"

STREAM_STATUS=$(aws kinesis describe-stream-summary --stream-name "$STREAM_NAME" \
  --region "$AWS_REGION" --query 'StreamDescriptionSummary.StreamStatus' \
  --output text 2>/dev/null || echo "MISSING")

if [[ "$STREAM_STATUS" == "ACTIVE" ]]; then
  ok "Stream ACTIVE"
elif [[ "$STREAM_STATUS" == "CREATING" ]]; then
  warn "Stream CREATING — waiting..."
  aws kinesis wait stream-exists --stream-name "$STREAM_NAME" --region "$AWS_REGION"
  ok "Stream ACTIVE"
elif [[ "$MODE" != "verify-only" ]]; then
  aws kinesis create-stream --stream-name "$STREAM_NAME" --shard-count 2 \
    --region "$AWS_REGION"
  aws kinesis wait stream-exists --stream-name "$STREAM_NAME" --region "$AWS_REGION"
  aws kinesis add-tags-to-stream --stream-name "$STREAM_NAME" \
    --tags "programme=accelya,owner=$LEARNER,environment=lab" --region "$AWS_REGION"
  ok "Created + ACTIVE"
fi
STREAM_ARN="arn:aws:kinesis:$AWS_REGION:$ACCOUNT_ID:stream/$STREAM_NAME"

# ──────────────────────────────────────────────────────────────────────────
# STAGE 5 — DynamoDB idempotency table
# ──────────────────────────────────────────────────────────────────────────
stage 5 "DynamoDB $DDB_TABLE (idempotency)"

DDB_STATUS=$(aws dynamodb describe-table --table-name "$DDB_TABLE" --region "$AWS_REGION" \
  --query 'Table.TableStatus' --output text 2>/dev/null || echo "MISSING")

if [[ "$DDB_STATUS" == "ACTIVE" ]]; then
  ok "Table ACTIVE"
elif [[ "$MODE" != "verify-only" ]]; then
  aws dynamodb create-table --table-name "$DDB_TABLE" \
    --attribute-definitions AttributeName=event_id,AttributeType=S \
    --key-schema AttributeName=event_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --tags "Key=programme,Value=accelya" "Key=owner,Value=$LEARNER" \
    --region "$AWS_REGION" >/dev/null
  aws dynamodb wait table-exists --table-name "$DDB_TABLE" --region "$AWS_REGION"
  ok "Created + ACTIVE"
fi

# ──────────────────────────────────────────────────────────────────────────
# STAGE 6 — SQS DLQ + review queue
# ──────────────────────────────────────────────────────────────────────────
stage 6 "SQS — $DLQ_NAME + $REVIEW_QUEUE"

for Q in "$DLQ_NAME" "$REVIEW_QUEUE"; do
  URL=$(aws sqs get-queue-url --queue-name "$Q" --region "$AWS_REGION" \
    --query QueueUrl --output text 2>/dev/null || echo "")
  if [[ -n "$URL" && "$URL" != "None" ]]; then
    ok "$Q exists: $URL"
  elif [[ "$MODE" != "verify-only" ]]; then
    URL=$(aws sqs create-queue --queue-name "$Q" \
      --tags "programme=accelya,owner=$LEARNER" \
      --region "$AWS_REGION" --query QueueUrl --output text)
    ok "Created $Q: $URL"
  fi
done
DLQ_URL=$(aws sqs get-queue-url --queue-name "$DLQ_NAME" --region "$AWS_REGION" \
  --query QueueUrl --output text)
REVIEW_URL=$(aws sqs get-queue-url --queue-name "$REVIEW_QUEUE" --region "$AWS_REGION" \
  --query QueueUrl --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url "$DLQ_URL" \
  --attribute-names QueueArn --region "$AWS_REGION" \
  --query 'Attributes.QueueArn' --output text)

# ──────────────────────────────────────────────────────────────────────────
# STAGE 7-12 — Lambdas + state machine + endpoint
# Delegated to per-day scripts (already idempotent + tested)
# ──────────────────────────────────────────────────────────────────────────
package_lambda() {
  # $1 = function name, $2 = src dir under src/, $3 = handler module
  local fn="$1" src="$2" handler="$3"
  local pkg="/tmp/m10-pkg-${fn}"
  local zip="/tmp/${fn}.zip"
  rm -rf "$pkg"; mkdir -p "$pkg/common"
  cp "$SRC_DIR/$src/handler.py" "$pkg/"
  cp "$SRC_DIR/common/exceptions.py" "$pkg/common/" 2>/dev/null || true
  cp "$SRC_DIR/common/observability.py" "$pkg/common/" 2>/dev/null || true
  touch "$pkg/common/__init__.py"
  # Powertools — installed only if Day-10 Lab-1 has happened; otherwise the
  # handler can run without it (observability.py is lazy-loaded)
  ( cd "$pkg" && zip -qr "$zip" . )
  echo "$zip"
}

deploy_lambda() {
  # $1 = function name, $2 = handler ref, $3 = zip path, $4 = env vars (one string), $5 = timeout, $6 = mem
  local fn="$1" handler="$2" zip="$3" env="$4" timeout="${5:-30}" mem="${6:-256}"
  if aws lambda get-function --function-name "$fn" --region "$AWS_REGION" >/dev/null 2>&1; then
    aws lambda update-function-code --function-name "$fn" \
      --zip-file "fileb://$zip" --region "$AWS_REGION" >/dev/null
    aws lambda wait function-updated --function-name "$fn" --region "$AWS_REGION"
    aws lambda update-function-configuration --function-name "$fn" \
      --environment "$env" --timeout "$timeout" --memory-size "$mem" \
      --tracing-config Mode=Active \
      --region "$AWS_REGION" >/dev/null
    ok "Updated $fn"
  else
    aws lambda create-function --function-name "$fn" \
      --runtime python3.12 --architectures x86_64 \
      --role "$ROLE_ARN" --handler "$handler" \
      --zip-file "fileb://$zip" --timeout "$timeout" --memory-size "$mem" \
      --environment "$env" \
      --tracing-config Mode=Active \
      --tags "programme=accelya,owner=$LEARNER,environment=lab" \
      --region "$AWS_REGION" >/dev/null
    aws lambda wait function-active --function-name "$fn" --region "$AWS_REGION"
    ok "Created $fn"
  fi
}

if [[ "$MODE" == "verify-only" ]]; then
  stage 7 "Verify Lambdas"
  for FN in "${LAMBDAS_ALL[@]}"; do
    STATE=$(aws lambda get-function --function-name "$FN" --region "$AWS_REGION" \
      --query 'Configuration.State' --output text 2>/dev/null || echo "MISSING")
    if [[ "$STATE" == "Active" ]]; then ok "$FN"; else err "$FN → $STATE"; fi
  done
else
  stage 7 "Lambdas 1-5 (foundational handlers)"

  # validator
  if [[ -f "$SRC_DIR/validator/handler.py" ]]; then
    ZIP=$(package_lambda "accelya-validator-${LEARNER}" validator handler.handler)
    deploy_lambda "accelya-validator-${LEARNER}" handler.handler "$ZIP" \
      "Variables={LEARNER=$LEARNER,BUCKET=$BUCKET,LOG_LEVEL=INFO}" 30 256
  else
    warn "src/validator/handler.py not found — skipping"
  fi

  # lander
  if [[ -f "$SRC_DIR/lander/handler.py" ]]; then
    ZIP=$(package_lambda "accelya-lander-${LEARNER}" lander handler.handler)
    deploy_lambda "accelya-lander-${LEARNER}" handler.handler "$ZIP" \
      "Variables={LEARNER=$LEARNER,BUCKET=$BUCKET,LOG_LEVEL=INFO}" 60 512
  fi

  # chunker
  if [[ -f "$SRC_DIR/chunker/handler.py" ]]; then
    ZIP=$(package_lambda "accelya-chunker-${LEARNER}" chunker handler.handler)
    deploy_lambda "accelya-chunker-${LEARNER}" handler.handler "$ZIP" \
      "Variables={LEARNER=$LEARNER,BUCKET=$BUCKET,LOG_LEVEL=INFO}" 60 512
  fi

  # dlq_replayer — the one we missed today
  if [[ -f "$SRC_DIR/dlq_replayer/handler.py" ]]; then
    # SNS escalation topic (idempotent)
    ESC_TOPIC_ARN=$(aws sns create-topic \
      --name "accelya-dlq-escalation-${LEARNER}" \
      --tags "Key=programme,Value=accelya" "Key=owner,Value=$LEARNER" \
      --region "$AWS_REGION" --query 'TopicArn' --output text)
    ZIP=$(package_lambda "accelya-dlq-replayer-${LEARNER}" dlq_replayer handler.handler)
    deploy_lambda "accelya-dlq-replayer-${LEARNER}" handler.handler "$ZIP" \
      "Variables={DLQ_URL=$DLQ_URL,MAIN_QUEUE_URL=$DLQ_URL,ESCALATION_TOPIC=$ESC_TOPIC_ARN,QUARANTINE_BUCKET=$BUCKET,LEARNER=$LEARNER,LOG_LEVEL=INFO}" 60 512
  fi

  # etl_json_to_parquet
  if [[ -f "$SRC_DIR/etl_json_to_parquet/handler.py" ]]; then
    ZIP=$(package_lambda "accelya-etl-json-to-parquet-${LEARNER}" etl_json_to_parquet handler.handler)
    deploy_lambda "accelya-etl-json-to-parquet-${LEARNER}" handler.handler "$ZIP" \
      "Variables={LEARNER=$LEARNER,BUCKET=$BUCKET,LOG_LEVEL=INFO}" 120 1024
  fi

  stage 8 "Lambdas 6-9 (Day-8 streaming)"
  # producer
  if [[ -f "$SRC_DIR/producer/handler.py" ]]; then
    ZIP=$(package_lambda "accelya-producer-${LEARNER}" producer handler.handler)
    deploy_lambda "accelya-producer-${LEARNER}" handler.handler "$ZIP" \
      "Variables={STREAM_NAME=$STREAM_NAME,LEARNER=$LEARNER,LOG_LEVEL=INFO}" 60 512
  fi

  # consumer (must come after state machine is created — we'll create SFN first below, then patch env)
  # bedrock_enrich
  if [[ -f "$SRC_DIR/bedrock_enrich/handler.py" ]]; then
    ZIP=$(package_lambda "accelya-bedrock-enrich-${LEARNER}" bedrock_enrich handler.handler)
    deploy_lambda "accelya-bedrock-enrich-${LEARNER}" handler.handler "$ZIP" \
      "Variables={SAMPLE_RATE=10,LEARNER=$LEARNER,LOG_LEVEL=INFO,BEDROCK_MODEL_ID=apac.anthropic.claude-3-5-sonnet-20241022-v2:0}" 60 512
  fi

  # persist_enriched
  if [[ -f "$SRC_DIR/persist_enriched/handler.py" ]]; then
    ZIP=$(package_lambda "accelya-persist-enriched-${LEARNER}" persist_enriched handler.handler)
    deploy_lambda "accelya-persist-enriched-${LEARNER}" handler.handler "$ZIP" \
      "Variables={LEARNER=$LEARNER,BUCKET=$BUCKET,LOG_LEVEL=INFO}" 60 512
  fi

  stage 9 "Step Functions $SM_NAME"
  # Render ASL with substitutions
  if [[ -f "$INFRA_DIR/inference-pipeline.asl.json" ]]; then
    sed -e "s/<learner>/$LEARNER/g" \
        -e "s/<account>/$ACCOUNT_ID/g" \
        "$INFRA_DIR/inference-pipeline.asl.json" > /tmp/${LEARNER}-asl.json
    # Validate first (D8 lesson)
    aws stepfunctions validate-state-machine-definition \
      --definition file:///tmp/${LEARNER}-asl.json --region "$AWS_REGION" \
      --query 'result' --output text >/tmp/asl-validate.txt
    if grep -q OK /tmp/asl-validate.txt; then
      ok "ASL validates"
    else
      err "ASL invalid:"; cat /tmp/asl-validate.txt; exit 1
    fi
    if aws stepfunctions describe-state-machine --state-machine-arn "$SM_ARN" \
        --region "$AWS_REGION" >/dev/null 2>&1; then
      aws stepfunctions update-state-machine --state-machine-arn "$SM_ARN" \
        --definition file:///tmp/${LEARNER}-asl.json \
        --tracing-configuration enabled=true \
        --region "$AWS_REGION" >/dev/null
      ok "Updated SM"
    else
      aws stepfunctions create-state-machine --name "$SM_NAME" \
        --definition file:///tmp/${LEARNER}-asl.json \
        --role-arn "$ROLE_ARN" \
        --tracing-configuration enabled=true \
        --tags "key=programme,value=accelya" "key=owner,value=$LEARNER" \
        --region "$AWS_REGION" >/dev/null
      ok "Created SM: $SM_ARN"
    fi
  else
    warn "infra/inference-pipeline.asl.json missing — skipping SFN"
  fi

  # Now deploy consumer with SM_ARN in env
  if [[ -f "$SRC_DIR/consumer/handler.py" ]]; then
    ZIP=$(package_lambda "accelya-consumer-${LEARNER}" consumer handler.handler)
    deploy_lambda "accelya-consumer-${LEARNER}" handler.handler "$ZIP" \
      "Variables={STATE_MACHINE_ARN=$SM_ARN,DDB_TABLE=$DDB_TABLE,LEARNER=$LEARNER,LOG_LEVEL=INFO}" 60 512
  fi

  stage 10 "Kinesis → consumer ESM (Event Source Mapping)"
  ESM_UUID=$(aws lambda list-event-source-mappings \
    --function-name "accelya-consumer-${LEARNER}" --region "$AWS_REGION" \
    --query "EventSourceMappings[?EventSourceArn=='$STREAM_ARN'].UUID | [0]" \
    --output text 2>/dev/null || echo "")
  if [[ -z "$ESM_UUID" || "$ESM_UUID" == "None" ]]; then
    aws lambda create-event-source-mapping \
      --function-name "accelya-consumer-${LEARNER}" \
      --event-source-arn "$STREAM_ARN" \
      --batch-size 10 --starting-position LATEST \
      --maximum-batching-window-in-seconds 5 \
      --maximum-retry-attempts 2 \
      --bisect-batch-on-function-error \
      --function-response-types ReportBatchItemFailures \
      --destination-config "{\"OnFailure\":{\"Destination\":\"$DLQ_ARN\"}}" \
      --region "$AWS_REGION" >/dev/null
    ok "Created ESM"
  else
    ok "ESM exists: $ESM_UUID"
  fi

  # ────────────────────────────────────────────────────────────────────
  # STAGE 11 — SageMaker endpoint (optional)
  # ────────────────────────────────────────────────────────────────────
  stage 11 "SageMaker endpoint $ENDPOINT_NAME"
  if [[ "$MODE" == "skip-endpoint" ]]; then
    warn "Skipping endpoint per --skip-endpoint flag."
    hint "Day-10 SageMaker dashboard widgets will show 'no data'. That's OK."
  else
    EP_STATUS=$(aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" \
      --region "$AWS_REGION" --query 'EndpointStatus' --output text 2>/dev/null || echo "MISSING")
    if [[ "$EP_STATUS" == "InService" ]]; then
      ok "Endpoint InService"
    elif [[ "$EP_STATUS" == "Creating" ]]; then
      warn "Endpoint Creating — waiting (~3-5 min)..."
      aws sagemaker wait endpoint-in-service --endpoint-name "$ENDPOINT_NAME" --region "$AWS_REGION"
      ok "Endpoint InService"
    else
      # Check sandbox-wide endpoint cap (1 per account)
      OTHER_EP=$(aws sagemaker list-endpoints --region "$AWS_REGION" \
        --query "Endpoints[?EndpointName!='$ENDPOINT_NAME'] | [0].EndpointName" \
        --output text 2>/dev/null || echo "")
      if [[ -n "$OTHER_EP" && "$OTHER_EP" != "None" ]]; then
        warn "Another endpoint exists ($OTHER_EP). Sandbox cap = 1 per account."
        hint "Either ask its owner to delete, or re-run with --skip-endpoint."
        exit 1
      fi
      # Delegate to existing deploy_m9_endpoint.sh
      if [[ -x "$SCRIPT_DIR/deploy_m9_endpoint.sh" ]]; then
        warn "Endpoint not present — invoking deploy_m9_endpoint.sh..."
        bash "$SCRIPT_DIR/deploy_m9_endpoint.sh" "$LEARNER" || {
          err "Endpoint deploy failed."
          hint "Re-run bootstrap with --skip-endpoint to continue without it."
          exit 1
        }
        ok "Endpoint created"
      else
        warn "deploy_m9_endpoint.sh missing — skipping"
      fi
    fi
  fi

  stage 12 "Predict wrapper Lambda"
  if [[ -f "$SRC_DIR/predict/handler.py" ]]; then
    ZIP=$(package_lambda "accelya-predict-cancel-risk-${LEARNER}" predict handler.handler)
    deploy_lambda "accelya-predict-cancel-risk-${LEARNER}" handler.handler "$ZIP" \
      "Variables={ENDPOINT_NAME=$ENDPOINT_NAME,CONFIDENCE_THRESHOLD=0.7,LEARNER=$LEARNER,LOG_LEVEL=INFO}" 45 512
  fi
fi

# ──────────────────────────────────────────────────────────────────────────
# STAGE 13 — Day-10 observability finishing touches
# (log retention 14d on all 10 + powertools layer hint)
# ──────────────────────────────────────────────────────────────────────────
stage 13 "Day-10 observability prep (log retention + TracingConfig sanity)"

for FN in "${LAMBDAS_ALL[@]}"; do
  if ! aws lambda get-function --function-name "$FN" --region "$AWS_REGION" >/dev/null 2>&1; then
    continue
  fi
  # Log retention
  aws logs create-log-group --log-group-name "/aws/lambda/$FN" \
    --region "$AWS_REGION" 2>/dev/null || true
  aws logs put-retention-policy --log-group-name "/aws/lambda/$FN" \
    --retention-in-days 14 --region "$AWS_REGION" 2>/dev/null || true
  # TracingConfig sanity (deploy_lambda set it; re-affirm)
  aws lambda update-function-configuration --function-name "$FN" \
    --tracing-config Mode=Active --region "$AWS_REGION" >/dev/null 2>&1 || true
done
ok "Log retention 14d + TracingConfig Active on all present Lambdas"

# ──────────────────────────────────────────────────────────────────────────
# FINAL SUMMARY
# ──────────────────────────────────────────────────────────────────────────
stage F "Summary — what you have right now"

printf "\n%-50s %s\n" "RESOURCE" "STATE"
printf "%-50s %s\n" "──────────────────────────────────────────────────" "─────────"
LAMBDA_COUNT=0
for FN in "${LAMBDAS_ALL[@]}"; do
  STATE=$(aws lambda get-function --function-name "$FN" --region "$AWS_REGION" \
    --query 'Configuration.State' --output text 2>/dev/null || echo "MISSING")
  [[ "$STATE" == "Active" ]] && LAMBDA_COUNT=$((LAMBDA_COUNT+1))
  printf "%-50s %s\n" "$FN" "$STATE"
done
printf "%-50s %s\n" "Step Function $SM_NAME" \
  "$(aws stepfunctions describe-state-machine --state-machine-arn $SM_ARN --region $AWS_REGION --query status --output text 2>/dev/null || echo MISSING)"
printf "%-50s %s\n" "Kinesis $STREAM_NAME" \
  "$(aws kinesis describe-stream-summary --stream-name $STREAM_NAME --region $AWS_REGION --query StreamDescriptionSummary.StreamStatus --output text 2>/dev/null || echo MISSING)"
printf "%-50s %s\n" "DDB $DDB_TABLE" \
  "$(aws dynamodb describe-table --table-name $DDB_TABLE --region $AWS_REGION --query Table.TableStatus --output text 2>/dev/null || echo MISSING)"
printf "%-50s %s\n" "SQS $DLQ_NAME" \
  "$([ -n "$DLQ_URL" ] && echo OK || echo MISSING)"
printf "%-50s %s\n" "SageMaker endpoint $ENDPOINT_NAME" \
  "$(aws sagemaker describe-endpoint --endpoint-name $ENDPOINT_NAME --region $AWS_REGION --query EndpointStatus --output text 2>/dev/null || echo NOT_DEPLOYED)"

echo ""
echo "Lambda count: $LAMBDA_COUNT / 10"

if [[ "$LAMBDA_COUNT" -lt 10 ]]; then
  warn "Not at 10/10. Day-10 deploy will fail pre-flight."
  hint "Investigate which Lambda is MISSING above; re-run this script."
  exit 2
fi

ok "Ready for Day-10 labs."
echo ""
echo "Next steps:"
echo "  1. Run the M10 deploy:"
echo "       bash trainer-deliverables/51_create_m10_observability.sh $LEARNER"
echo "  2. Open module-10-labs.md and proceed with Lab 1 sub-steps A → B → C."
echo "  3. At end of day, run teardown:"
echo "       bash scripts/bootstrap_day10.sh $LEARNER --teardown"
