#!/usr/bin/env bash
# Day 6 Lab 1 — provision 2 Glue Databases + 2 Glue Crawlers + service role.
#
# What this creates (per learner):
#   - IAM role:           AWSGlueServiceRole-Accelya-<learner>
#   - Glue Database:      accelya_validated_<learner>     (JSON A/B target)
#   - Glue Database:      accelya_curated_<learner>       (Parquet primary)
#   - Glue Database:      accelya_enriched_<learner>      (scaffold, Day 9)
#   - Glue Database:      accelya_quarantine_<learner>    (scaffold)
#   - Glue Crawler:       validated-json-crawler-<learner>
#                         target: s3://<bucket>/validated/<learner>/validated_settlement_json/
#   - Glue Crawler:       curated-parquet-crawler-<learner>
#                         target: s3://<bucket>/curated/settlement/
#
# Usage:
#   bash scripts/provision_m6_glue.sh <learner>
#   e.g. bash scripts/provision_m6_glue.sh jai
#
# Idempotent — safe to re-run.

set -euo pipefail

LEARNER="${1:-}"
if [[ -z "$LEARNER" ]]; then
  echo "ERROR: learner name required. Usage: $0 <learner>" >&2
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
BUCKET="${BUCKET_NAME:-accelya-airline-data-ap-south-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

GLUE_ROLE="AWSGlueServiceRole-Accelya-${LEARNER}"
DB_VALID="accelya_validated_${LEARNER}"
DB_CUR="accelya_curated_${LEARNER}"
DB_ENR="accelya_enriched_${LEARNER}"
DB_QUAR="accelya_quarantine_${LEARNER}"
CRAWLER_JSON="validated-json-crawler-${LEARNER}"
CRAWLER_PARQ="curated-parquet-crawler-${LEARNER}"

echo "═══════════════════════════════════════════════════════════════"
echo " Day 6 Lab 1 — provision Glue Catalog resources"
echo " Region:  $REGION"
echo " Bucket:  s3://$BUCKET"
echo " Learner: $LEARNER"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. IAM Glue service role ──────────────────────────────────────────────
echo ""
echo "[1/4] IAM Glue service role: $GLUE_ROLE"

GLUE_TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"glue.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

if aws iam get-role --role-name "$GLUE_ROLE" >/dev/null 2>&1; then
  echo "  ✓ Role $GLUE_ROLE exists"
else
  aws iam create-role --role-name "$GLUE_ROLE" \
    --assume-role-policy-document "$GLUE_TRUST" \
    --description "M6 Glue service role for Accelya ${LEARNER}" \
    --tags Key=programme,Value=accelya-agentic-aws Key=module,Value=m6 \
           Key=learner,Value="$LEARNER" >/dev/null
  echo "  ✓ Role created"
fi

aws iam attach-role-policy --role-name "$GLUE_ROLE" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole" 2>/dev/null || true

GLUE_S3_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "JsonCrawlerReadValidated",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::${BUCKET}/validated/${LEARNER}/*"]
    },
    {
      "Sid": "JsonCrawlerListValidated",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::${BUCKET}",
      "Condition": {
        "StringLike": {"s3:prefix": ["validated/${LEARNER}/*"]}
      }
    },
    {
      "Sid": "ParquetCrawlerReadCurated",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::${BUCKET}/curated/settlement/*"]
    },
    {
      "Sid": "ParquetCrawlerListCurated",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::${BUCKET}",
      "Condition": {
        "StringLike": {"s3:prefix": ["curated/settlement/*"]}
      }
    }
  ]
}
EOF
)
echo "$GLUE_S3_POLICY" | aws iam put-role-policy \
  --role-name "$GLUE_ROLE" \
  --policy-name "M6CrawlerS3Policy" \
  --policy-document file:///dev/stdin
echo "  ✓ S3 read policy attached (scoped to $LEARNER prefix)"

GLUE_ROLE_ARN=$(aws iam get-role --role-name "$GLUE_ROLE" --query 'Role.Arn' --output text)
echo "  Role ARN: $GLUE_ROLE_ARN"

# Brief sleep for IAM propagation before first Crawler use
sleep 5

# ── 2. Glue databases ─────────────────────────────────────────────────────
echo ""
echo "[2/4] Glue Databases"

for DB in "$DB_VALID" "$DB_CUR" "$DB_ENR" "$DB_QUAR"; do
  if aws glue get-database --name "$DB" --region "$REGION" >/dev/null 2>&1; then
    echo "  ✓ Database $DB exists"
  else
    aws glue create-database \
      --database-input "Name=$DB,Description=Accelya M6 — $LEARNER" \
      --region "$REGION"
    echo "  ✓ Database $DB created"
  fi
done

# ── 3. Crawlers ───────────────────────────────────────────────────────────
echo ""
echo "[3/4] Glue Crawlers"

# 3a. JSON Crawler (validated zone)
JSON_TARGET="s3://${BUCKET}/validated/${LEARNER}/validated_settlement_json/"
JSON_CRAWLER_CONFIG=$(cat <<EOF
{
  "Name": "${CRAWLER_JSON}",
  "Role": "${GLUE_ROLE_ARN}",
  "DatabaseName": "${DB_VALID}",
  "Description": "M6 — JSON crawler over validated zone (A/B comparison vs Parquet)",
  "Targets": {
    "S3Targets": [
      { "Path": "${JSON_TARGET}" }
    ]
  },
  "SchemaChangePolicy": {
    "UpdateBehavior": "UPDATE_IN_DATABASE",
    "DeleteBehavior": "LOG"
  },
  "RecrawlPolicy": {
    "RecrawlBehavior": "CRAWL_EVERYTHING"
  },
  "Tags": {
    "programme": "accelya-agentic-aws",
    "module":    "m6",
    "learner":   "${LEARNER}"
  }
}
EOF
)

if aws glue get-crawler --name "$CRAWLER_JSON" --region "$REGION" >/dev/null 2>&1; then
  echo "  ✓ Crawler $CRAWLER_JSON exists; updating..."
  echo "$JSON_CRAWLER_CONFIG" | aws glue update-crawler --cli-input-json file:///dev/stdin --region "$REGION" 2>&1 \
    || echo "    (update may be a no-op if config unchanged)"
else
  echo "$JSON_CRAWLER_CONFIG" | aws glue create-crawler --cli-input-json file:///dev/stdin --region "$REGION"
  echo "  ✓ Crawler $CRAWLER_JSON created"
fi

# 3b. Parquet Crawler (curated zone)
PARQ_TARGET="s3://${BUCKET}/curated/settlement/"
PARQ_CRAWLER_CONFIG=$(cat <<EOF
{
  "Name": "${CRAWLER_PARQ}",
  "Role": "${GLUE_ROLE_ARN}",
  "DatabaseName": "${DB_CUR}",
  "Description": "M6 — Parquet crawler over curated zone (primary read target)",
  "Targets": {
    "S3Targets": [
      { "Path": "${PARQ_TARGET}" }
    ]
  },
  "SchemaChangePolicy": {
    "UpdateBehavior": "UPDATE_IN_DATABASE",
    "DeleteBehavior": "LOG"
  },
  "RecrawlPolicy": {
    "RecrawlBehavior": "CRAWL_EVERYTHING"
  },
  "Tags": {
    "programme": "accelya-agentic-aws",
    "module":    "m6",
    "learner":   "${LEARNER}"
  }
}
EOF
)

if aws glue get-crawler --name "$CRAWLER_PARQ" --region "$REGION" >/dev/null 2>&1; then
  echo "  ✓ Crawler $CRAWLER_PARQ exists; updating..."
  echo "$PARQ_CRAWLER_CONFIG" | aws glue update-crawler --cli-input-json file:///dev/stdin --region "$REGION" 2>&1 \
    || echo "    (update may be a no-op if config unchanged)"
else
  echo "$PARQ_CRAWLER_CONFIG" | aws glue create-crawler --cli-input-json file:///dev/stdin --region "$REGION"
  echo "  ✓ Crawler $CRAWLER_PARQ created"
fi

# ── 4. Sanity report ──────────────────────────────────────────────────────
echo ""
echo "[4/4] Sanity report"
echo "  Databases:"
for DB in "$DB_VALID" "$DB_CUR" "$DB_ENR" "$DB_QUAR"; do
  STATE=$(aws glue get-database --name "$DB" --region "$REGION" \
    --query 'Database.Name' --output text 2>/dev/null || echo "MISSING")
  printf "    %-40s %s\n" "$DB" "$STATE"
done
echo "  Crawlers:"
for CR in "$CRAWLER_JSON" "$CRAWLER_PARQ"; do
  STATE=$(aws glue get-crawler --name "$CR" --region "$REGION" \
    --query 'Crawler.State' --output text 2>/dev/null || echo "MISSING")
  printf "    %-40s %s\n" "$CR" "$STATE"
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " ✅ Day 6 Lab 1 provisioning complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Re-stage Day 5 validated/ output into Hive-style paths:"
echo "     aws s3 cp s3://$BUCKET/validated/$LEARNER/2026-W19/chunk-0001.jsonl \\"
echo "       s3://$BUCKET/validated/$LEARNER/validated_settlement_json/source_system=BSP/ingest_date=2026-05-09/chunk-0001.jsonl"
echo ""
echo "  2. Run the JSON Crawler:"
echo "     aws glue start-crawler --name $CRAWLER_JSON --region $REGION"
echo ""
echo "  3. Wait for completion (~3 min), then inspect:"
echo "     aws glue get-tables --database-name $DB_VALID --region $REGION"
echo ""
echo "  4. Lab 2: deploy the ETL Lambda + run Parquet Crawler against curated/"
