#!/usr/bin/env bash
# scripts/cleanup_module1.sh — Day 1 end-of-module cleanup.
# Linux/WSL/macOS compatible.

set -e

LEARNER="${LEARNER:-$(whoami)}"
REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
BUCKET="accelya-airline-data-ap-south-1"

echo "🧹  Cleaning up Module 1 for learner: $LEARNER"
echo "    Region: $REGION"
echo "    Bucket: s3://$BUCKET/learner-sandbox/$LEARNER/"
echo ""

# ── 1. Empty your learner prefix in S3 ────────────────────────────────
echo "1. Emptying S3 learner prefix..."
aws s3 rm "s3://$BUCKET/learner-sandbox/$LEARNER/" \
  --recursive --region "$REGION" 2>&1 | tail -5 || true
echo "   ✓ Done"
echo ""

# ── 2. Confirm no runaway Bedrock invocations ─────────────────────────
echo "2. Checking Bedrock invocation count in last hour..."
START=$(python3 -c 'from datetime import datetime,timedelta,timezone;print((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat().replace("+00:00","Z"))')
END=$(python3 -c 'from datetime import datetime,timezone;print(datetime.now(timezone.utc).isoformat().replace("+00:00","Z"))')
aws cloudwatch get-metric-statistics \
  --namespace AWS/Bedrock --metric-name Invocations \
  --start-time "$START" --end-time "$END" \
  --period 300 --statistics Sum \
  --region "$REGION" 2>&1 | head -20 || true
echo ""

# ── 3. Stage outputs in your branch ───────────────────────────────────
echo "3. Staging Module 1 outputs to git..."
git add prompts/ outputs/ reviews/ HITL_REVIEW.md 2>&1 | head -5 || true
if git diff --cached --quiet; then
  echo "   (nothing to commit)"
else
  git commit -m "module-1: complete" 2>&1 | head -3
  echo "   ✓ Committed"
fi
echo ""

# ── 4. Push & remind to open PR ───────────────────────────────────────
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "no-git-branch")
if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "no-git-branch" ]; then
  echo "4. Pushing branch '$BRANCH'..."
  git push origin "$BRANCH" 2>&1 | tail -5 || true
  echo "   ✓ Pushed. Open a PR on GitHub:"
  echo "     https://github.com/<org>/accelya-agentic-aws/compare/main...$BRANCH"
else
  echo "4. Skipping git push (current branch: $BRANCH)"
fi
echo ""

# ── 5. Verify ─────────────────────────────────────────────────────────
echo "5. Verifying cleanup..."
REMAINING=$(aws s3 ls "s3://$BUCKET/learner-sandbox/$LEARNER/" --recursive --region "$REGION" 2>/dev/null | wc -l)
if [ "$REMAINING" -eq 0 ]; then
  echo "   ✅  ALL CLEAR — S3 prefix empty for $LEARNER"
else
  echo "   ⚠  $REMAINING object(s) still in s3://$BUCKET/learner-sandbox/$LEARNER/"
  echo "      Re-run step 1, then this verification."
fi
echo ""
echo "Module 1 cleanup complete."
