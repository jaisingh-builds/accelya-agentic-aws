#!/usr/bin/env bash
# scripts/cleanup_module3.sh — Day 3 end-of-module cleanup.
#
# Day 3 is the foundation day: NO new AWS resources provisioned.
# This script verifies that's the case + commits any pending artefacts.
#
# Linux / WSL / macOS compatible.

set -e

LEARNER="${LEARNER:-$(whoami)}"
REGION="${AWS_DEFAULT_REGION:-ap-south-1}"

echo "🧹  Cleaning up Module 3 for learner: $LEARNER"
echo "    Region: $REGION"
echo ""

# ── 1. Verify no AWS resources accidentally provisioned ───────────────────
echo "1. Verifying no new AWS resources (Day 3 should be foundation only)..."

LAMBDA_COUNT=$(aws lambda list-functions \
  --region "$REGION" \
  --query "length(Functions[?contains(FunctionName,'$LEARNER')])" \
  --output text 2>/dev/null || echo "?")
echo "   Lambda count for $LEARNER: $LAMBDA_COUNT  (expected: 1 = D2 starter validator)"

if [ "$LAMBDA_COUNT" != "1" ] && [ "$LAMBDA_COUNT" != "?" ]; then
  echo "   ⚠  Unexpected Lambda count. Day 3 should not have provisioned new Lambdas."
  echo "      List your functions: aws lambda list-functions --region $REGION \\"
  echo "        --query \"Functions[?contains(FunctionName,'$LEARNER')].FunctionName\""
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
echo "   Expected: Invocations ~1-4 today. Cumulative ~2-5 of 50 (~45+ left for D4-D12)."
echo ""

# ── 3. Stage Day 3 artefacts in git ───────────────────────────────────────
echo "3. Staging Module 3 artefacts to git..."
git add .windsurfrules \
        prompts/v1_arch_options.txt \
        prompts/v2_validator.txt \
        outputs/m3-arch-options.json \
        reviews/m3-cascade-rules-test.md \
        reviews/m3-arch-scorecard.csv \
        reviews/m3-arch-decision-MR.md \
        reviews/HITL_REVIEW-weak_validator.md \
        reviews/HITL_REVIEW-strong_validator.md \
        reviews/m3-prompt-refinement-diff.md \
        scripts/generate_architectures.py \
        src/weak_validator/ \
        src/strong_validator/ \
        prompts/.gitkeep reviews/.gitkeep design/.gitkeep \
        2>&1 | head -10 || true

if git diff --cached --quiet; then
  echo "   (nothing to commit — already pushed)"
else
  git commit -m "module-3: foundations complete (prompts + reviews + .windsurfrules v1)" 2>&1 | head -3
  echo "   ✓ Committed"
fi
echo ""

# ── 4. Push branch ────────────────────────────────────────────────────────
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "no-git-branch")
if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "no-git-branch" ]; then
  echo "4. Pushing branch '$BRANCH'..."
  git push origin "$BRANCH" 2>&1 | tail -3 || true
  echo "   ✓ Pushed. Open a PR on GitHub:"
  echo "     https://github.com/jaisingh-builds/accelya-agentic-aws/compare/main...$BRANCH"
else
  echo "4. Skipping git push (current branch: $BRANCH)"
fi
echo ""

# ── 5. Verify artefacts present ───────────────────────────────────────────
echo "5. Verifying Day 3 artefacts present..."
MISSING=0
for f in \
    ".windsurfrules" \
    "prompts/v1_arch_options.txt" \
    "prompts/v2_validator.txt" \
    "outputs/m3-arch-options.json" \
    "reviews/m3-arch-scorecard.csv" \
    "reviews/m3-arch-decision-MR.md" \
    "reviews/HITL_REVIEW-weak_validator.md" \
    "reviews/HITL_REVIEW-strong_validator.md" \
    "reviews/m3-prompt-refinement-diff.md" \
    "src/weak_validator/handler.py" \
    "src/strong_validator/handler.py"
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
  echo "   ✅  ALL CLEAR — all Day 3 artefacts present"
else
  echo "   ⚠  $MISSING artefact(s) missing. Complete the labs before pushing PR."
fi
echo ""

echo "Module 3 cleanup complete. Day 4 inherits .windsurfrules v1 + audit folders."
