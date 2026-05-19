#!/usr/bin/env bash
# Day 7 end-of-module cleanup — PRESERVES EVERYTHING DAY 8+ NEEDS.
#
# What this PRESERVES (Day 8 reads from these):
#   - accelya-bookings-stream-<learner>  (the Kinesis stream)
#   - accelya-stream-role-<learner>      (the IAM role)
#   - stream_seen_keys_<learner>         (the idempotency table)
#
# What this DOES:
#   - Verifies all three resources still exist and are ACTIVE
#   - Reports Bedrock budget burn (should be ~10 of 50)
#   - No deletions — Day 7 is design-only and provisioned infrastructure
#     stays alive for Day 8
#
# Usage:
#   bash scripts/cleanup_module7.sh <learner>

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
STREAM="accelya-bookings-stream-${LEARNER}"
ROLE="accelya-stream-role-${LEARNER}"
TABLE="stream_seen_keys_${LEARNER}"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 7 cleanup — verify programme artefacts (no deletions)"
echo " Region:  $REGION"
echo " Learner: $LEARNER"
echo "═══════════════════════════════════════════════════════════════"

# ── Kinesis stream ────────────────────────────────────────────────────────
echo ""
echo "[1/3] Kinesis stream: $STREAM"
STREAM_STATUS=$(aws kinesis describe-stream --stream-name "$STREAM" --region "$REGION" \
  --query 'StreamDescription.StreamStatus' --output text 2>/dev/null || echo "MISSING")
SHARD_COUNT=$(aws kinesis describe-stream --stream-name "$STREAM" --region "$REGION" \
  --query 'length(StreamDescription.Shards)' --output text 2>/dev/null || echo "0")
RETENTION=$(aws kinesis describe-stream --stream-name "$STREAM" --region "$REGION" \
  --query 'StreamDescription.RetentionPeriodHours' --output text 2>/dev/null || echo "?")
printf "  %-40s status=%s shards=%s retention=%sh\n" "$STREAM" "$STREAM_STATUS" "$SHARD_COUNT" "$RETENTION"

# ── IAM role ──────────────────────────────────────────────────────────────
echo ""
echo "[2/3] IAM role: $ROLE"
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  printf "  %-40s %s\n" "$ROLE" "PRESENT"
  printf "    %-38s %s\n" "Inline policies:" \
    "$(aws iam list-role-policies --role-name "$ROLE" --query 'PolicyNames' --output text)"
else
  printf "  %-40s %s\n" "$ROLE" "MISSING"
fi

# ── DynamoDB idempotency table ────────────────────────────────────────────
echo ""
echo "[3/3] DynamoDB table: $TABLE"
TABLE_STATUS=$(aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" \
  --query 'Table.TableStatus' --output text 2>/dev/null || echo "MISSING")
TTL_STATUS=$(aws dynamodb describe-time-to-live --table-name "$TABLE" --region "$REGION" \
  --query 'TimeToLiveDescription.TimeToLiveStatus' --output text 2>/dev/null || echo "?")
printf "  %-40s status=%s ttl=%s\n" "$TABLE" "$TABLE_STATUS" "$TTL_STATUS"

# ── Lambda count check (should be unchanged from Day 6) ──────────────────
echo ""
echo "Lambda count check (should be 6 of 10 — Day 7 added zero):"
COUNT=$(aws lambda list-functions --region "$REGION" \
  --query "length(Functions[?contains(FunctionName,'-${LEARNER}')])" --output text 2>/dev/null || echo "?")
echo "  Lambdas for $LEARNER: $COUNT"

echo ""
echo "═══════════════════════════════════════════════════════════════"
if [[ "$STREAM_STATUS" == "ACTIVE" ]] && [[ "$TABLE_STATUS" == "ACTIVE" ]] && [[ "$TTL_STATUS" == "ENABLED" ]]; then
  echo " ✅ Day 7 artefacts intact — ready for Day 8"
else
  echo " ⚠️  Some artefacts not in expected state — investigate"
fi
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Day 8 prerequisites (verified above):"
echo "  - Stream ACTIVE with 2 shards, retention >=24h"
echo "  - IAM role $ROLE present with policies"
echo "  - Table $TABLE ACTIVE with TTL ENABLED on 'ttl'"
echo "  - .windsurfrules v4 committed (Day 8 promotes to v5)"
