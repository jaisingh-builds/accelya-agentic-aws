#!/usr/bin/env bash
# preflight-lambda-cap.sh — fail CI early if app-stack deploy would breach the cap.
#
# WHY: AWS sandbox has no hard Lambda cap on free tier, but the programme tally
# is a soft scoping rule (10 from Days 1-9 + 1 pretraffic-hook = 11). If a
# learner's MR adds a new Lambda accidentally (e.g. Cascade scaffolding a helper),
# we want to catch it BEFORE sam deploy rolls forward with an unintended 12th.
#
# Hard limit enforced: 12 (= 11 + 1 buffer for the migration-gate snapshot pattern).
#
# Usage in CI:
#   bash scripts/preflight-lambda-cap.sh "$CI_COMMIT_REF_SLUG"
#
# Local debug:
#   bash scripts/preflight-lambda-cap.sh trainer
#   bash scripts/preflight-lambda-cap.sh trainer --delete-manual   # Day-11 migration gate
#
# Exit codes:
#   0  → cap respected; CI may proceed
#   1  → would breach cap; CI must abort
#   2  → AWS API error (network / creds); CI may retry

set -euo pipefail

LEARNER="${1:-}"
MODE="check"
[[ "${2:-}" == "--delete-manual" ]] && MODE="delete-manual"

if [[ -z "$LEARNER" ]]; then
  echo "Usage: $0 <learner> [--delete-manual]"
  exit 1
fi

REGION="${AWS_REGION:-ap-south-1}"
HARD_CAP=12

# ── Count existing Lambdas matching learner suffix ───────────────────────
EXISTING=$(aws lambda list-functions --region "$REGION" \
  --query "Functions[?contains(FunctionName,'-${LEARNER}')].FunctionName" \
  --output text 2>/dev/null) || {
    echo "❌ AWS list-functions failed (creds/network)"; exit 2;
  }
EXISTING_COUNT=$(echo "$EXISTING" | wc -w | tr -d ' ')

echo "─── Preflight Lambda cap check ─────────────────────────────────"
echo "  Learner:       $LEARNER"
echo "  Region:        $REGION"
echo "  Hard cap:      $HARD_CAP"
echo "  Existing:      $EXISTING_COUNT functions matching -${LEARNER}"
if [[ "$EXISTING_COUNT" -gt 0 ]]; then
  echo "  Functions:"
  for FN in $EXISTING; do echo "    - $FN"; done
fi

# ── Count Lambdas the about-to-deploy app stack will create ──────────────
# Heuristic: grep AWS::Serverless::Function from infra/template-app.yaml
TEMPLATE_LAMBDAS=0
if [[ -f "infra/template-app.yaml" ]]; then
  TEMPLATE_LAMBDAS=$(grep -c 'Type: AWS::Serverless::Function' infra/template-app.yaml || true)
fi
echo "  Template adds: $TEMPLATE_LAMBDAS new functions (from template-app.yaml)"

# ── Project total ────────────────────────────────────────────────────────
# Conservative: if EXISTING already has the function name from the template,
# count it as an update (not new). For preflight, assume worst case = add.
PROJECTED=$((EXISTING_COUNT + TEMPLATE_LAMBDAS))
echo "  Projected total post-deploy (worst case): $PROJECTED"

# ── Delete-manual mode (Day-11 Lab 1 migration gate; trainer-only) ──────
if [[ "$MODE" == "delete-manual" ]]; then
  echo ""
  echo "─── MIGRATION GATE: snapshot + delete manual Lambdas ───────────"
  mkdir -p reviews/m11-pre-migration
  for FN in $EXISTING; do
    SNAPSHOT="reviews/m11-pre-migration/${FN}.json"
    echo "  Snapshot: $FN → $SNAPSHOT"
    aws lambda get-function-configuration --function-name "$FN" \
      --region "$REGION" --output json > "$SNAPSHOT"
    echo "  Delete:   $FN"
    aws lambda delete-function --function-name "$FN" --region "$REGION"
  done
  REMAINING=$(aws lambda list-functions --region "$REGION" \
    --query "Functions[?contains(FunctionName,'-${LEARNER}')]" --output text | wc -l)
  if [[ "$REMAINING" -ne 0 ]]; then
    echo "❌ Expected 0 Lambdas after migration; found $REMAINING"
    exit 1
  fi
  echo "  ✓ All manual Lambdas snapshotted + deleted. Safe to sam deploy."
  exit 0
fi

# ── Standard check mode ──────────────────────────────────────────────────
if [[ "$PROJECTED" -gt "$HARD_CAP" ]]; then
  echo ""
  echo "❌ BLOCK: projected $PROJECTED Lambdas would breach cap $HARD_CAP."
  echo ""
  echo "   Options:"
  echo "   1. If existing Lambdas are stale (manual deploys from previous day):"
  echo "        bash scripts/preflight-lambda-cap.sh $LEARNER --delete-manual"
  echo "      then re-run CI."
  echo ""
  echo "   2. If the template legitimately adds a new function, justify in MR description"
  echo "      and trainer raises HARD_CAP for this MR."
  exit 1
fi

echo ""
echo "  ✓ Preflight OK ($PROJECTED ≤ $HARD_CAP). Proceeding with sam deploy."
exit 0
