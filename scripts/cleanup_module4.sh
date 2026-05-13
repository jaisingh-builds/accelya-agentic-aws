#!/usr/bin/env bash
# scripts/cleanup_module4.sh — Day 4 end-of-module cleanup.
#
# Day 4 is the second foundation day: NO new AWS resources provisioned.
# This script verifies that's the case + commits any pending artefacts.

set -e

LEARNER="${LEARNER:-$(whoami)}"
REGION="${AWS_DEFAULT_REGION:-ap-south-1}"

echo "🧹  Cleaning up Module 4 for learner: $LEARNER"
echo "    Region: $REGION"
echo ""

# ── 1. Verify no AWS resources accidentally provisioned ───────────────────
echo "1. Verifying no new AWS resources (Day 4 is design-only)..."

LAMBDA_COUNT=$(aws lambda list-functions \
  --region "$REGION" \
  --query "length(Functions[?contains(FunctionName,'$LEARNER')])" \
  --output text 2>/dev/null || echo "?")
echo "   Lambda count for $LEARNER: $LAMBDA_COUNT  (expected: 1 = D2 starter)"

DDB_COUNT=$(aws dynamodb list-tables \
  --region "$REGION" \
  --query "length(TableNames[?contains(@,'$LEARNER')])" \
  --output text 2>/dev/null || echo "?")
echo "   DynamoDB tables for $LEARNER: $DDB_COUNT  (expected: 0 — provisioned Day 5)"

if [ "$LAMBDA_COUNT" != "1" ] && [ "$LAMBDA_COUNT" != "?" ]; then
  echo "   ⚠  Unexpected Lambda count. Day 4 should not have provisioned new Lambdas."
fi
if [ "$DDB_COUNT" != "0" ] && [ "$DDB_COUNT" != "?" ]; then
  echo "   ⚠  DynamoDB tables exist. Day 4 is design-only; tables ship Day 5."
fi
echo ""

# ── 2. Bedrock budget check ───────────────────────────────────────────────
echo "2. Bedrock invocation budget (today)..."
PROFILE=apac.anthropic.claude-3-5-sonnet-20241022-v2:0
START=$(python3 -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).isoformat().replace("+00:00","Z"))')
END=$(python3 -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).isoformat().replace("+00:00","Z"))')

for METRIC in Invocations InputTokenCount OutputTokenCount; do
  echo "   $METRIC:"
  aws cloudwatch get-metric-statistics \
    --namespace AWS/Bedrock --metric-name "$METRIC" \
    --dimensions Name=ModelId,Value="$PROFILE" \
    --start-time "$START" --end-time "$END" \
    --period 3600 --statistics Sum \
    --region "$REGION" 2>&1 | head -10 | sed 's/^/      /'
done
echo ""
echo "   Expected: Invocations = 0 today (D4 is design-only)."
echo ""

# ── 3. Stage Day 4 artefacts in git ───────────────────────────────────────
echo "3. Staging Module 4 artefacts to git..."
git add design/m4-batch-pipeline-design.md \
        design/m4-failure-modes.md \
        reviews/HITL_REVIEW-m4-design.md \
        reviews/m4-windsurfrules-test.md \
        .windsurfrules \
        prompts/v7_design.txt \
        2>&1 | head -10 || true

if git diff --cached --quiet; then
  echo "   (nothing to commit — already pushed)"
else
  git commit -m "module-4: design doc + failure-mode catalogue + .windsurfrules v1-final" 2>&1 | head -3
  echo "   ✓ Committed"
fi
echo ""

# ── 4. Push branch ────────────────────────────────────────────────────────
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "no-git-branch")
if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "no-git-branch" ]; then
  echo "4. Pushing branch '$BRANCH'..."
  git push origin "$BRANCH" 2>&1 | tail -3 || true
  echo "   ✓ Pushed. PR URL:"
  echo "     https://github.com/jaisingh-builds/accelya-agentic-aws/compare/main...$BRANCH"
else
  echo "4. Skipping git push (current branch: $BRANCH)"
fi
echo ""

# ── 5. Verify artefacts present ───────────────────────────────────────────
echo "5. Verifying Day 4 artefacts present..."
MISSING=0
for f in \
    ".windsurfrules" \
    "prompts/v7_design.txt" \
    "design/m4-batch-pipeline-design.md" \
    "design/m4-failure-modes.md" \
    "reviews/HITL_REVIEW-m4-design.md" \
    "reviews/m4-windsurfrules-test.md"
do
  if [ -f "$f" ]; then
    echo "   ✓ $f"
  else
    echo "   ✗ $f  MISSING"
    MISSING=$((MISSING + 1))
  fi
done
echo ""

if [ "$MISSING" -eq 0 ]; then
  echo "   ✅  ALL CLEAR — all Day 4 artefacts present. Ready for Day 5."
else
  echo "   ⚠  $MISSING artefact(s) missing. Complete the labs before pushing PR."
fi
echo ""

echo "Module 4 cleanup complete. Day 5 inherits design doc + .windsurfrules v1-final."
