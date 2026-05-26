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
# IMPORTANT: only delete Lambdas that are NOT already CFN-managed by
# accelya-app-<learner>. Earlier versions of this script blindly deleted
# every accelya-*-<learner> Lambda, which destroyed CFN-managed Lambdas
# on Path-A re-deploys (the original 3-Lambda slice from Day 11 Lab 2).
# CFN's stack-resources view persists even after the actual resource is
# deleted, producing stack drift that's hard to recover from.
if [[ "$MODE" == "delete-manual" ]]; then
  echo ""
  echo "─── MIGRATION GATE: snapshot + delete manual Lambdas ───────────"
  mkdir -p reviews/m11-pre-migration

  # Get the set of Lambda names CFN currently manages in accelya-app-<learner>
  APP_STACK="accelya-app-${LEARNER}"
  CFN_MANAGED=$(aws cloudformation list-stack-resources \
    --stack-name "$APP_STACK" --region "$REGION" \
    --query "StackResourceSummaries[?ResourceType=='AWS::Lambda::Function'].PhysicalResourceId" \
    --output text 2>/dev/null | tr '\t' '\n' | sort -u)

  if [[ -n "$CFN_MANAGED" ]]; then
    echo "  CFN-managed (will SKIP):"
    echo "$CFN_MANAGED" | sed 's/^/    - /'
  fi

  DELETED_COUNT=0
  for FN in $EXISTING; do
    if echo "$CFN_MANAGED" | grep -qx "$FN"; then
      echo "  Skip (CFN-managed):  $FN"
      continue
    fi
    SNAPSHOT="reviews/m11-pre-migration/${FN}.json"
    echo "  Snapshot: $FN → $SNAPSHOT"
    aws lambda get-function-configuration --function-name "$FN" \
      --region "$REGION" --output json > "$SNAPSHOT"
    echo "  Delete (manual):     $FN"
    aws lambda delete-function --function-name "$FN" --region "$REGION"
    DELETED_COUNT=$((DELETED_COUNT + 1))
  done
  echo "  ✓ Migration gate complete: $DELETED_COUNT manual Lambdas removed, CFN-managed preserved."
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
