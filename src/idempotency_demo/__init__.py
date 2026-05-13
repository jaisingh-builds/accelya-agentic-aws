"""
src/idempotency_demo/ — Day 4 OPTIONAL trainer-side demo.

Demonstrates the 4 idempotency guards from Concept 5 live:
  - row#<file_key>:<line_no>      (TTL 30d)
  - file#<file_sha256>            (TTL 90d)
  - canonical#<canonical_hash>    (TTL 90d)
  - business#<settlement_id>      (TTL 30d)

NOT for learner deployment — Day 4 is design-only. This is a TRAINER demo
artefact so the cohort can SEE the table + guards working before they design
their own Day 5 implementation.

Run script: trainer-deliverables/26_create_m4_idempotency_demo.sh
"""
