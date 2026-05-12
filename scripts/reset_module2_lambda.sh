#!/usr/bin/env bash
# scripts/reset_module2_lambda.sh — Reset learner code on the pre-created Module 2 Lambda.
#
# What it does:
#   Packages src/validator/handler.py and pushes it to accelya-m2-validator-<learner>.
#   This restores the trainer-provided baseline if you made edits during Lab 3
#   experimentation and want to reset before Day 3.
#
# Usage:
#   bash scripts/reset_module2_lambda.sh <learner>
#
# Idempotent — safe to re-run.

set -e

LEARNER="${1:-${LEARNER:-$(whoami)}}"
REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
FUNCTION_NAME="accelya-m2-validator-${LEARNER}"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
HANDLER="$REPO_ROOT/src/validator/handler.py"
ZIP_FILE="/tmp/${FUNCTION_NAME}-baseline.zip"

if [ ! -f "$HANDLER" ]; then
  echo "❌ Handler not found at $HANDLER"
  exit 1
fi

echo "Resetting $FUNCTION_NAME to baseline handler..."
echo "  Handler: $HANDLER"
echo "  Region:  $REGION"

# 1. Repackage from baseline source
(cd "$(dirname "$HANDLER")" && zip -j "$ZIP_FILE" "$(basename "$HANDLER")" >/dev/null)
echo "  ✓ Repackaged: $ZIP_FILE ($(du -h "$ZIP_FILE" | cut -f1))"

# 2. Check function exists
if ! aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "  ⚠  Lambda $FUNCTION_NAME not found in $REGION."
  echo "      Either the trainer hasn't provisioned it yet, or your name doesn't match the suffix."
  echo "      Skipping reset (Day 3 still works without resetting code)."
  exit 0
fi

# 3. Push code update
aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --zip-file "fileb://$ZIP_FILE" \
  --region "$REGION" >/dev/null
echo "  ✓ Code update submitted"

# 4. Wait for update to settle
aws lambda wait function-updated-v2 \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION"
echo "  ✓ Lambda is back to baseline. Ready for Day 3."

# 5. Confirm via get-function
CURRENT_SHA=$(aws lambda get-function \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --query 'Configuration.CodeSha256' --output text)
echo "  Current CodeSha256: $CURRENT_SHA"
