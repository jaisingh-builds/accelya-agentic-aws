#!/usr/bin/env bash
# Day 5 Lab 1 — provision the SINGLE DynamoDB idempotency table.
#
# This is the only AWS resource Lab 1 creates BEFORE deploying Lambdas.
# Lab 2 + Lab 3 provision their own queues / topics inline in their playbooks.
#
# Usage:
#   bash scripts/provision_m5_resources.sh <learner>
#   e.g. bash scripts/provision_m5_resources.sh jai
#
# Idempotent — safe to re-run; if the table already exists in ACTIVE state, exits 0.

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
TABLE="idempotency_keys_${LEARNER}"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 5 Lab 1 — provision idempotency table"
echo " Region: $REGION"
echo " Table:  $TABLE"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Check whether the table already exists
if aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" >/dev/null 2>&1; then
  STATUS=$(aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" \
    --query 'Table.TableStatus' --output text)
  if [[ "$STATUS" == "ACTIVE" ]]; then
    echo "✓ Table $TABLE already ACTIVE — nothing to do."
  else
    echo "✓ Table $TABLE exists; status=$STATUS — waiting for ACTIVE..."
    aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"
    echo "✓ Table $TABLE now ACTIVE."
  fi
else
  echo "Creating table $TABLE (PAY_PER_REQUEST)..."
  aws dynamodb create-table \
    --table-name "$TABLE" \
    --attribute-definitions AttributeName=pk,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" \
    --tags Key=programme,Value=accelya-agentic-aws \
           Key=module,Value=m5 \
           Key=learner,Value="$LEARNER" \
    >/dev/null
  echo "  Waiting for ACTIVE..."
  aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"
  echo "✓ Table $TABLE created and ACTIVE."
fi

# Enable TTL on the `ttl` attribute (idempotent — checks current state)
TTL_STATUS=$(aws dynamodb describe-time-to-live --table-name "$TABLE" --region "$REGION" \
  --query 'TimeToLiveDescription.TimeToLiveStatus' --output text 2>/dev/null || echo "DISABLED")

if [[ "$TTL_STATUS" == "ENABLED" ]]; then
  echo "✓ TTL already ENABLED on attribute 'ttl'."
else
  echo "Enabling TTL on attribute 'ttl'..."
  aws dynamodb update-time-to-live \
    --table-name "$TABLE" \
    --time-to-live-specification "Enabled=true, AttributeName=ttl" \
    --region "$REGION" >/dev/null
  echo "✓ TTL ENABLED."
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ Provisioning complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Verify with:"
echo "  aws dynamodb describe-table --table-name $TABLE --region $REGION \\"
echo "    --query 'Table.[TableName,TableStatus]'"
echo "  aws dynamodb describe-time-to-live --table-name $TABLE --region $REGION"
echo ""
echo "Next: deploy Lambdas (chunker, validator_m5, lander) — see"
echo "      docs/lab-guides/module-5-labs.md Lab 1 step 5."
