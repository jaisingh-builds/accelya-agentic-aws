#!/usr/bin/env bash
# scripts/verify_cleanup.sh — Day 1+ post-cleanup verification.
# Prints "ALL CLEAR" if your learner prefix is empty.

set -e

LEARNER="${LEARNER:-$(whoami)}"
REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
BUCKET="accelya-airline-data-ap-south-1"

REMAINING=$(aws s3 ls "s3://$BUCKET/learner-sandbox/$LEARNER/" --recursive --region "$REGION" 2>/dev/null | wc -l | tr -d ' ')

if [ "$REMAINING" -eq 0 ]; then
  echo "✅  ALL CLEAR — s3://$BUCKET/learner-sandbox/$LEARNER/ is empty."
  exit 0
else
  echo "❌  $REMAINING object(s) still in s3://$BUCKET/learner-sandbox/$LEARNER/"
  aws s3 ls "s3://$BUCKET/learner-sandbox/$LEARNER/" --recursive --region "$REGION"
  exit 1
fi
