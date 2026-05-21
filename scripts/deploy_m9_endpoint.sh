#!/usr/bin/env bash
# Day 9 Lab 1 — deploy SageMaker Serverless endpoint.
#
# What this creates:
#   1. IAM role accelya-sagemaker-role-<learner>   (model S3 read + CW logs)
#   2. SageMaker Model    accelya-cancel-risk-model-<learner>
#   3. SageMaker EndpointConfig  accelya-cancel-risk-config-<learner>
#                                  ServerlessConfig: MemorySizeInMB=1024, MaxConcurrency=5
#   4. SageMaker Endpoint  accelya-cancel-risk-<learner>
#   Waits for EndpointStatus=InService (~3-5 min).
#
# Prerequisites:
#   - Trainer artefact at s3://<bucket>/models/cancel-risk/v1.2.3/model.tar.gz
#   - .windsurfrules v6 committed
#
# Usage:
#   bash scripts/deploy_m9_endpoint.sh <learner>
#
# Idempotent — re-run safely.

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
BUCKET="${BUCKET_NAME:-accelya-airline-data-ap-south-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

MODEL_NAME="accelya-cancel-risk-model-${LEARNER}"
CONFIG_NAME="accelya-cancel-risk-config-${LEARNER}"
ENDPOINT_NAME="accelya-cancel-risk-${LEARNER}"
ROLE_NAME="accelya-sagemaker-role-${LEARNER}"

# Inference image — scikit-learn 1.2-1 CPU.
# IMPORTANT: SageMaker's framework-container ECR registry is per-region.
#            For ap-south-1 the account is 720646828776 (NOT 246618743249 — that's us-east-1).
# Source of truth: https://github.com/aws/deep-learning-containers/blob/master/available_images.md
# Override via SKLEARN_IMAGE env var if the lookup ever drifts.
case "$REGION" in
  ap-south-1)     SKLEARN_REGISTRY="720646828776" ;;
  us-east-1)      SKLEARN_REGISTRY="683313688378" ;;
  us-west-2)      SKLEARN_REGISTRY="246618743249" ;;
  eu-west-1)      SKLEARN_REGISTRY="141502667606" ;;
  ap-southeast-1) SKLEARN_REGISTRY="121021644041" ;;
  *)              SKLEARN_REGISTRY="${SKLEARN_REGISTRY:-720646828776}" ;;
esac
INFERENCE_IMAGE="${SKLEARN_IMAGE:-${SKLEARN_REGISTRY}.dkr.ecr.${REGION}.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3}"
MODEL_ARTEFACT="s3://${BUCKET}/models/cancel-risk/v1.2.3/model.tar.gz"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 9 Lab 1 — deploy SageMaker Serverless endpoint"
echo " Region:    $REGION"
echo " Learner:   $LEARNER"
echo " Endpoint:  $ENDPOINT_NAME"
echo " Image:     $INFERENCE_IMAGE"
echo " Artefact:  $MODEL_ARTEFACT"
echo "═══════════════════════════════════════════════════════════════"

# ── Pre-flight ────────────────────────────────────────────────────────────
if ! aws s3 ls "$MODEL_ARTEFACT" --region "$REGION" >/dev/null 2>&1; then
  echo "❌ Model artefact missing: $MODEL_ARTEFACT"
  echo "   Trainer must upload before Lab 1."
  exit 1
fi

# Sandbox-cap check: no other endpoint with our learner suffix
EXISTING=$(aws sagemaker list-endpoints --region "$REGION" \
  --query "Endpoints[?contains(EndpointName,'$LEARNER')].EndpointName" --output text)
if [[ -n "$EXISTING" && "$EXISTING" != "$ENDPOINT_NAME" ]]; then
  echo "❌ Other endpoint(s) exist for this learner: $EXISTING"
  echo "   Sandbox cap = 1. Delete first: bash scripts/reset_module9_endpoint.sh $LEARNER"
  exit 1
fi

# ── 1. IAM SageMaker execution role ──────────────────────────────────────
echo ""
echo "[1/4] IAM role: $ROLE_NAME"
SM_TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"sagemaker.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "  ✓ Role exists"
else
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$SM_TRUST" \
    --description "M9 SageMaker execution role for Accelya ${LEARNER}" \
    --tags Key=programme,Value=accelya-agentic-aws Key=module,Value=m9 \
           Key=learner,Value="$LEARNER" >/dev/null
  echo "  ✓ Role created"
fi

SM_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ModelArtefactRead",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::${BUCKET}",
        "arn:aws:s3:::${BUCKET}/models/*"
      ]
    },
    {
      "Sid": "CWLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "*"
    },
    {
      "Sid": "ECRPull",
      "Effect": "Allow",
      "Action": ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability",
                 "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"],
      "Resource": "*"
    }
  ]
}
EOF
)
echo "$SM_POLICY" > /tmp/m9-sm-policy.json
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name "M9SageMakerPolicy" \
  --policy-document "file:///tmp/m9-sm-policy.json"
echo "  ✓ Policy attached"

SAGEMAKER_ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
sleep 5  # IAM propagation

# ── 2. SageMaker Model ────────────────────────────────────────────────────
echo ""
echo "[2/4] SageMaker Model: $MODEL_NAME"
if aws sagemaker describe-model --model-name "$MODEL_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "  ✓ Model exists (delete via reset script if config changed)"
else
  aws sagemaker create-model \
    --model-name "$MODEL_NAME" \
    --primary-container "Image=$INFERENCE_IMAGE,ModelDataUrl=$MODEL_ARTEFACT" \
    --execution-role-arn "$SAGEMAKER_ROLE_ARN" \
    --region "$REGION" \
    --tags Key=programme,Value=accelya-agentic-aws Key=module,Value=m9 \
           Key=learner,Value="$LEARNER" >/dev/null
  echo "  ✓ Model created"
fi

# ── 3. Endpoint Config ────────────────────────────────────────────────────
echo ""
echo "[3/4] Endpoint Config: $CONFIG_NAME"
if aws sagemaker describe-endpoint-config --endpoint-config-name "$CONFIG_NAME" \
     --region "$REGION" >/dev/null 2>&1; then
  echo "  ✓ Config exists"
else
  PRODUCTION_VARIANTS=$(cat <<EOF
[
  {
    "VariantName": "AllTraffic",
    "ModelName":   "$MODEL_NAME",
    "InitialVariantWeight": 1.0,
    "ServerlessConfig": {
      "MemorySizeInMB": 1024,
      "MaxConcurrency": 5
    }
  }
]
EOF
)
  echo "$PRODUCTION_VARIANTS" > /tmp/m9-pv.json
  aws sagemaker create-endpoint-config \
    --endpoint-config-name "$CONFIG_NAME" \
    --production-variants "file:///tmp/m9-pv.json" \
    --region "$REGION" \
    --tags Key=programme,Value=accelya-agentic-aws Key=module,Value=m9 \
           Key=learner,Value="$LEARNER" >/dev/null
  echo "  ✓ Endpoint config created (Memory=1024, MaxConcurrency=5)"
fi

# ── 4. Endpoint ───────────────────────────────────────────────────────────
echo ""
echo "[4/4] Endpoint: $ENDPOINT_NAME"
if aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" \
     --region "$REGION" >/dev/null 2>&1; then
  STATUS=$(aws sagemaker describe-endpoint --endpoint-name "$ENDPOINT_NAME" \
    --region "$REGION" --query 'EndpointStatus' --output text)
  echo "  ✓ Endpoint exists (status=$STATUS)"
else
  aws sagemaker create-endpoint \
    --endpoint-name "$ENDPOINT_NAME" \
    --endpoint-config-name "$CONFIG_NAME" \
    --region "$REGION" \
    --tags Key=programme,Value=accelya-agentic-aws Key=module,Value=m9 \
           Key=learner,Value="$LEARNER" >/dev/null
  echo "  → Endpoint creating; waiting for InService (~3-5 min)..."
  aws sagemaker wait endpoint-in-service \
    --endpoint-name "$ENDPOINT_NAME" --region "$REGION"
  echo "  ✓ Endpoint InService"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ Day 9 endpoint deployed"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Verify with:"
echo "  aws sagemaker describe-endpoint --endpoint-name $ENDPOINT_NAME \\"
echo "    --region $REGION --query 'EndpointStatus'"
echo ""
echo "Smoke test (invoke + base64-decode response):"
echo "  PAYLOAD='{\"booking_id\":\"BK-TEST-001\",\"fare_amount\":2845.00,\"refund_lag_hours\":2.5,\"prior_cancels\":0}'"
echo "  aws sagemaker-runtime invoke-endpoint \\"
echo "    --endpoint-name $ENDPOINT_NAME \\"
echo "    --content-type application/json --accept application/json \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --body \"\$PAYLOAD\" --region $REGION /tmp/m9-resp.json"
echo "  cat /tmp/m9-resp.json | python3 -m json.tool"
echo ""
echo "Cold-start metric:"
echo "  aws cloudwatch get-metric-statistics --namespace AWS/SageMaker \\"
echo "    --metric-name ModelSetupTime \\"
echo "    --dimensions Name=EndpointName,Value=$ENDPOINT_NAME \\"
echo "                 Name=VariantName,Value=AllTraffic \\"
echo "    --start-time \$(date -u -v-10M +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u --date='10 minutes ago' +%Y-%m-%dT%H:%M:%S) \\"
echo "    --end-time \$(date -u +%Y-%m-%dT%H:%M:%S) --period 60 \\"
echo "    --statistics Maximum --region $REGION"
echo ""
echo "Next: Lab 2 — deploy wrapper Lambda + update state machine"
echo "Cleanup (CRITICAL at end of Lab 3): bash scripts/reset_module9_endpoint.sh $LEARNER"
