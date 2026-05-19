#!/usr/bin/env bash
# Day 7 Lab 1 — provision 1 Kinesis stream + 1 IAM role + 1 DynamoDB idempotency table.
#
# What this creates (per learner):
#   - Kinesis stream:  accelya-bookings-stream-<learner>  (2 shards, 24h retention)
#   - IAM role:        accelya-stream-role-<learner>
#                        Trust: lambda.amazonaws.com
#                        Policies: kinesis:Put/Get/Describe, dynamodb:PutItem/GetItem
#   - DynamoDB table:  stream_seen_keys_<learner>
#                        PK: pk (String)
#                        TTL: ttl attribute (7 days for cancellation events)
#                        Billing: PAY_PER_REQUEST
#
# Day 8 producer + consumer Lambdas will assume the IAM role and write/read
# the stream + idempotency table.
#
# Usage:
#   bash scripts/provision_m7_stream.sh <learner>
#
# Idempotent — safe to re-run.

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

STREAM="accelya-bookings-stream-${LEARNER}"
ROLE="accelya-stream-role-${LEARNER}"
DDB_TABLE="stream_seen_keys_${LEARNER}"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 7 Lab 1 — provision streaming infrastructure"
echo " Region:   $REGION"
echo " Stream:   $STREAM (2 shards)"
echo " Role:     $ROLE"
echo " Table:    $DDB_TABLE"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. Kinesis stream ────────────────────────────────────────────────────
echo ""
echo "[1/3] Kinesis stream: $STREAM"
if aws kinesis describe-stream --stream-name "$STREAM" --region "$REGION" >/dev/null 2>&1; then
  echo "  ✓ Stream $STREAM exists"
  STATUS=$(aws kinesis describe-stream --stream-name "$STREAM" --region "$REGION" \
    --query 'StreamDescription.StreamStatus' --output text)
  SHARDS=$(aws kinesis describe-stream --stream-name "$STREAM" --region "$REGION" \
    --query 'length(StreamDescription.Shards)' --output text)
  echo "    Status: $STATUS / Shards: $SHARDS"
else
  echo "  → Creating stream..."
  aws kinesis create-stream \
    --stream-name "$STREAM" \
    --shard-count 2 \
    --region "$REGION"
  echo "  → Waiting for ACTIVE..."
  aws kinesis wait stream-exists --stream-name "$STREAM" --region "$REGION"
  echo "  ✓ Stream ACTIVE with 2 shards"
fi

# ── 2. IAM role ──────────────────────────────────────────────────────────
echo ""
echo "[2/3] IAM role: $ROLE"

TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  echo "  ✓ Role $ROLE exists"
else
  aws iam create-role --role-name "$ROLE" \
    --assume-role-policy-document "$TRUST" \
    --description "M7 streaming role for Accelya ${LEARNER}" \
    --tags Key=programme,Value=accelya-agentic-aws Key=module,Value=m7 \
           Key=learner,Value="$LEARNER" >/dev/null
  echo "  ✓ Role created"
fi

aws iam attach-role-policy --role-name "$ROLE" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true

STREAM_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "KinesisStreamAccess",
      "Effect": "Allow",
      "Action": [
        "kinesis:PutRecord", "kinesis:PutRecords",
        "kinesis:GetRecords", "kinesis:GetShardIterator",
        "kinesis:DescribeStream", "kinesis:DescribeStreamSummary",
        "kinesis:ListShards", "kinesis:SubscribeToShard"
      ],
      "Resource": "arn:aws:kinesis:${REGION}:${ACCOUNT_ID}:stream/${STREAM}"
    },
    {
      "Sid": "DDBStreamIdempotency",
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem", "dynamodb:GetItem"],
      "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${DDB_TABLE}"
    },
    {
      "Sid": "S3QuarantineWrite",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::accelya-airline-data-${REGION}/quarantine/${LEARNER}/stream_invalid/*"
    },
    {
      "Sid": "CloudWatchEMF",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
                 "cloudwatch:PutMetricData"],
      "Resource": "*"
    }
  ]
}
EOF
)
echo "$STREAM_POLICY" > /tmp/m7-stream-policy.json
aws iam put-role-policy \
  --role-name "$ROLE" \
  --policy-name "M7StreamPolicy" \
  --policy-document "file:///tmp/m7-stream-policy.json"
echo "  ✓ Inline policy attached (Kinesis + DDB + S3 quarantine + CW)"
ROLE_ARN=$(aws iam get-role --role-name "$ROLE" --query 'Role.Arn' --output text)
echo "  Role ARN: $ROLE_ARN"

# ── 3. DynamoDB idempotency table ────────────────────────────────────────
echo ""
echo "[3/3] DynamoDB table: $DDB_TABLE"
if aws dynamodb describe-table --table-name "$DDB_TABLE" --region "$REGION" >/dev/null 2>&1; then
  STATUS=$(aws dynamodb describe-table --table-name "$DDB_TABLE" --region "$REGION" \
    --query 'Table.TableStatus' --output text)
  if [[ "$STATUS" == "ACTIVE" ]]; then
    echo "  ✓ Table $DDB_TABLE already ACTIVE"
  else
    echo "  ✓ Table $DDB_TABLE exists (status=$STATUS); waiting..."
    aws dynamodb wait table-exists --table-name "$DDB_TABLE" --region "$REGION"
  fi
else
  aws dynamodb create-table \
    --table-name "$DDB_TABLE" \
    --attribute-definitions AttributeName=pk,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" \
    --tags Key=programme,Value=accelya-agentic-aws Key=module,Value=m7 \
           Key=learner,Value="$LEARNER" >/dev/null
  aws dynamodb wait table-exists --table-name "$DDB_TABLE" --region "$REGION"
  echo "  ✓ Table created and ACTIVE"
fi

TTL_STATUS=$(aws dynamodb describe-time-to-live --table-name "$DDB_TABLE" --region "$REGION" \
  --query 'TimeToLiveDescription.TimeToLiveStatus' --output text 2>/dev/null || echo "DISABLED")
if [[ "$TTL_STATUS" == "ENABLED" ]]; then
  echo "  ✓ TTL already ENABLED on attribute 'ttl'"
else
  aws dynamodb update-time-to-live --table-name "$DDB_TABLE" \
    --time-to-live-specification "Enabled=true,AttributeName=ttl" \
    --region "$REGION" >/dev/null
  echo "  ✓ TTL ENABLED on attribute 'ttl'"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ Day 7 Lab 1 provisioning complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Verify with:"
echo "  aws kinesis describe-stream --stream-name $STREAM --region $REGION \\"
echo "    --query 'StreamDescription.[StreamStatus,length(Shards)]'"
echo "  aws iam get-role --role-name $ROLE --query 'Role.Arn'"
echo "  aws dynamodb describe-time-to-live --table-name $DDB_TABLE --region $REGION"
echo ""
echo "Smoke test (PutRecord/GetRecords):"
echo "  aws kinesis put-record --stream-name $STREAM --region $REGION \\"
echo "    --partition-key 'AI:2026-05-09' --data 'eyJzbW9rZSI6dHJ1ZX0='"
echo ""
echo "  ITER=\$(aws kinesis get-shard-iterator --stream-name $STREAM --region $REGION \\"
echo "    --shard-id shardId-000000000000 --shard-iterator-type TRIM_HORIZON \\"
echo "    --query ShardIterator --output text)"
echo "  aws kinesis get-records --shard-iterator \$ITER --region $REGION --query 'Records[].Data'"
echo ""
echo "Next: Lab 2 (producer contract design, paper exercise)"
