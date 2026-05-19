#!/usr/bin/env bash
# Upload the Day 6 synthetic settlements dataset (from the repo) into the
# learner's `validated/<learner>/validated_settlement_json/` Hive layout.
#
# Source:  starter-repo/data/m6-settlements/source_system=*/ingest_date=*/part-*.jsonl
# Target:  s3://<bucket>/validated/<learner>/validated_settlement_json/source_system=*/ingest_date=*/part-*.jsonl
#
# Total:   16 partition files, ~48K rows, ~15 MB
#
# Usage:
#   bash scripts/upload_m6_settlements.sh <learner>
#
# Idempotent. `aws s3 sync` only re-uploads changed files.

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
BUCKET="${BUCKET_NAME:-accelya-airline-data-ap-south-1}"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
DATA_DIR="$SCRIPT_DIR/../data/m6-settlements"

if [[ ! -d "$DATA_DIR" ]]; then
  echo "ERROR: data directory missing: $DATA_DIR" >&2
  echo "       Run: python3 scripts/generate_m6_settlements.py" >&2
  exit 1
fi

TARGET_PREFIX="s3://${BUCKET}/validated/${LEARNER}/validated_settlement_json"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 6 — upload synthetic settlements (~48K rows / 15 MB)"
echo " Region:  $REGION"
echo " Learner: $LEARNER"
echo " From:    $DATA_DIR"
echo " To:      $TARGET_PREFIX/"
echo "═══════════════════════════════════════════════════════════════"

aws s3 sync \
  "$DATA_DIR/" \
  "$TARGET_PREFIX/" \
  --region "$REGION" \
  --exclude "*.md"

echo ""
echo "✓ Upload complete. Inspect:"
echo ""
echo "  aws s3 ls $TARGET_PREFIX/ --recursive --region $REGION | head -20"
echo ""
echo "Partition layout in S3 (should show 16 partitions):"
aws s3 ls "$TARGET_PREFIX/" --recursive --region "$REGION" \
  | awk '{print $4}' \
  | sed -E "s|.*/validated_settlement_json/||" \
  | awk -F'/' '{print $1"/"$2}' \
  | sort -u
echo ""
echo "Next: run the JSON Crawler"
echo "  aws glue start-crawler --name validated-json-crawler-$LEARNER --region $REGION"
