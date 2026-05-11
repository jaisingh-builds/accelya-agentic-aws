"""
src/enricher/ — Day 2 showcase Lambda (companion to validator).

A simple validator + Bedrock-powered enricher: takes one record, asks Bedrock
to classify the cancellation reason, returns the enriched record.

Used by the trainer during Day 2 to showcase:
  - Lambda + Bedrock together (a preview of Day 3+).
  - Different memory/timeout profile vs the validator.
  - Logging through CloudWatch Insights, same correlation_id pattern.
"""
