#!/usr/bin/env bash
# scripts/cleanup_module2.sh — Day 2 end-of-module cleanup.
# Linux / WSL / macOS compatible.

set -e

LEARNER="${LEARNER:-$(whoami)}"
REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
BUCKET="accelya-airline-data-ap-south-1"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

echo "🧹  Cleaning up Module 2 for learner: $LEARNER"
echo "    Region: $REGION"
echo "    Bucket: s3://$BUCKET/"
echo ""

# ── 1. Reset learner code on the pre-created Lambda ───────────────────────
# (do NOT delete the function — trainer keeps it for Day 3)
echo "1. Resetting learner Lambda code to baseline..."
if [ -f "$SCRIPT_DIR/reset_module2_lambda.sh" ]; then
  bash "$SCRIPT_DIR/reset_module2_lambda.sh" "$LEARNER" || echo "   ⚠ Reset script failed; skipping (Day 3 still works)"
else
  echo "   (reset_module2_lambda.sh not found; skipping)"
fi
echo ""

# ── 2. CloudWatch log group — preserve (Day 3 reviews logs) ───────────────
echo "2. Preserving CloudWatch log group (logs reviewed in Day 3)..."
echo "   → /aws/lambda/accelya-m2-validator-$LEARNER (kept)"
echo ""

# ── 3. Empty Lab 2 staging prefix ─────────────────────────────────────────
echo "3. Emptying Lab 2 staging area..."
aws s3 rm "s3://$BUCKET/learner-sandbox/$LEARNER/" \
  --recursive --region "$REGION" 2>&1 | tail -3 || true
echo "   ✓ learner-sandbox/$LEARNER/ emptied"
echo ""

# ── 4. Empty your learner prefixes — raw/, validated/, quarantine/ ────────
echo "4. Emptying your raw/, validated/, quarantine/ prefixes..."
for ZONE in raw validated quarantine; do
  COUNT=$(aws s3 ls "s3://$BUCKET/$ZONE/$LEARNER/" --recursive --region "$REGION" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$COUNT" -gt 0 ]; then
    aws s3 rm "s3://$BUCKET/$ZONE/$LEARNER/" \
      --recursive --region "$REGION" 2>&1 | tail -3 || true
    echo "   ✓ $ZONE/$LEARNER/ emptied ($COUNT objects removed)"
  else
    echo "   ✓ $ZONE/$LEARNER/ already empty"
  fi
done
echo ""

# ── 5. Stage outputs in your branch ───────────────────────────────────────
echo "5. Staging Module 2 outputs to git..."
git add docs/m2-iam-verification.md docs/m2-s3-layout.md \
        reviews/HITL_REVIEW-m2-validator.md HITL_REVIEW.md \
        src/validator/handler.py 2>&1 | head -5 || true
if git diff --cached --quiet; then
  echo "   (nothing to commit)"
else
  git commit -m "module-2: complete (IAM verify + S3 layout + validator deployed + HITL scored)" 2>&1 | head -3
  echo "   ✓ Committed"
fi
echo ""

# ── 6. Push & remind to open PR ───────────────────────────────────────────
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "no-git-branch")
if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "no-git-branch" ]; then
  echo "6. Pushing branch '$BRANCH'..."
  git push origin "$BRANCH" 2>&1 | tail -3 || true
  echo "   ✓ Pushed. Open a PR on GitHub:"
  echo "     https://github.com/jaisingh-builds/accelya-agentic-aws/compare/main...$BRANCH"
else
  echo "6. Skipping git push (current branch: $BRANCH)"
fi
echo ""

# ── 7. Verify cleanup ─────────────────────────────────────────────────────
echo "7. Verifying cleanup..."
TOTAL_REMAINING=0
for ZONE in raw validated quarantine learner-sandbox; do
  COUNT=$(aws s3 ls "s3://$BUCKET/$ZONE/$LEARNER/" --recursive --region "$REGION" 2>/dev/null | wc -l | tr -d ' ')
  TOTAL_REMAINING=$((TOTAL_REMAINING + COUNT))
done

if [ "$TOTAL_REMAINING" -eq 0 ]; then
  echo "   ✅  ALL CLEAR — all learner prefixes empty for $LEARNER"
else
  echo "   ⚠  $TOTAL_REMAINING object(s) still in learner prefixes."
  echo "       Re-run cleanup or inspect with:"
  echo "       aws s3 ls s3://$BUCKET/raw/$LEARNER/ --recursive --region $REGION"
fi
echo ""

# ── Lambda state check ────────────────────────────────────────────────────
echo "Lambda state (should remain present for Day 3):"
aws lambda get-function \
  --function-name "accelya-m2-validator-$LEARNER" \
  --region "$REGION" \
  --query 'Configuration.{Name:FunctionName, State:State, LastUpdateStatus:LastUpdateStatus}' \
  --output table 2>/dev/null || echo "   (Lambda not found; expected if you're using the trainer demo function instead)"
echo ""

echo "Module 2 cleanup complete."
