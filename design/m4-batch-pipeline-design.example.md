# M4 — Batch Pipeline Design (Reference Example)

> **Trainer reference.** This is what a passing design doc looks like.
> Learner deliverable: `design/m4-batch-pipeline-design.md` on `module-4-<learner>`.
> Aim for ~800 words total; this example is ~900.

---

## 1. Context

Accelya processes airline settlement files (BSP cycles) weekly. Each file is
~80MB JSON, ~50k rows, arriving at `s3://accelya-airline-data-ap-south-1/raw/BSP/<date>/`
every Tuesday 02:00 UTC. The pipeline validates each row against a fixed schema,
deduplicates against four idempotency guards, lands valid rows in `validated/`,
and routes failures to `quarantine/<reason>/`. Output is the input to Day 6's
curator, which produces partitioned Parquet for Athena.

## 2. Four-zone S3 model

| Zone | Contract |
|---|---|
| **raw/** | Append-only; schema-on-read. Source-owned; cohort-shared read-only. |
| **validated/** | Schema-on-write. Every row matches the published schema. |
| **quarantine/** | Failed rows, organised by failure reason in subfolders. |
| **curated/** | Partitioned Parquet, Athena-ready. Output of Day 6 curator. |

Each zone makes specific guarantees (above) and EXPLICITLY makes no promise about
upstream/downstream behaviour outside its contract.

## 3. S3 layout

```
Bucket: accelya-airline-data-ap-south-1 (ap-south-1)

raw/BSP/2026-05-08/m4-settlement-batch-001.json           # cohort-shared, read-only

validated/<learner>/BSP/2026-05-08/m4-settlement-batch-001.jsonl
  # JSONL — D5 promotes to curated/*.parquet

quarantine/<learner>/<reason>/2026-05-08/...
  # reasons: schema_drift, partial, malformed, business_rule_failed
  # NOT quarantined: duplicates (DynamoDB no-op), late events (validated/ flagged)

curated/settlement/ingest_date=2026-05-08/source_system=BSP/part-0001.parquet
```

## 4. Data flow

```
BSP feed (Tuesday 02:00 UTC, ~80MB)
  → S3 raw/BSP/<date>/<file>.json
    → S3 ObjectCreated event → EventBridge → Step Functions StartExecution
      → [chunker Lambda]  splits 80MB into ~10 chunks (5-10MB each, ~5k rows each)
      → [Map state]  invokes validator Lambda per chunk in parallel (max concurrency 4)
        → [validator Lambda] per chunk:
            for each row:
              1. schema_check(row) → if fail → quarantine/schema_drift/
              2. claim('row#' + file_key + ':' + line_no, 30d) → DynamoDB
                 → if duplicate → skip silently
              3. parse_check(row) → if fail → quarantine/malformed/
              4. business_rule_check(row) → if fail → quarantine/business_rule_failed/
              5. write validated/<learner>/<source>/<date>/...jsonl
      → [lander Lambda]  aggregates Map output; writes file-level manifest
```

EventBridge scheduled checker fires daily at 03:00 UTC to verify manifest arrival.
Missing feed → source_outage incident via SNS (paged; not quarantined).

## 5. Failure-mode catalogue

| Mode | Catch point | Lands in |
|---|---|---|
| 1. Schema drift | `schema_check(row)` in validator | `quarantine/<learner>/schema_drift/<date>/` |
| 2. Partial write | `manifest_row_count_check()` in lander | `quarantine/<learner>/partial/<date>/` |
| 3a. Dup (same file replay) | `claim('row#' + file_key + ':' + line_no)` | DDB no-op (silent skip) |
| 3b. Dup (new filename, same bytes) | `claim('file#' + file_sha256)` | DDB no-op + audit log |
| 3c. Dup (rows reordered/reformatted) | `claim('canonical#' + canonical_manifest_hash)` | DDB no-op + audit log |
| 3d. Dup (business event re-arrival) | `claim('business#' + settlement_id)` | DDB no-op + audit log |
| 4. Late event | `event_date < ingest_date - 30d` check | `validated/` with `is_late=true` flag |
| 5. Malformed row | `json.loads(row)` raises | `quarantine/<learner>/malformed/<date>/` |
| 6. Source outage | EventBridge scheduled checker | SNS → on-call paged (no quarantine) |

## 6. Idempotency strategy

**One DynamoDB table; four guards; PK prefixes route.**

```python
TABLE: idempotency_keys_<learner>
ATTRIBUTES:
  pk            String  = '<guard>#<key>'    # PK
  processed_at  Number  = epoch seconds
  outcome       String  = 'validated' | 'quarantined' | 'duplicate'
  ttl           Number  = processed_at + retention_seconds
WRITE: PutItem(pk=prefixed_key, ConditionExpression='attribute_not_exists(pk)')
       success → process; ConditionalCheckFailedException → duplicate; skip silently
```

```
'row#<file_key>:<line_no>'            → TTL 30d  (row replay)
'file#<file_sha256>'                  → TTL 90d  (file-byte duplicate)
'canonical#<canonical_manifest_hash>' → TTL 90d  (row-set logical duplicate)
'business#<settlement_id>'            → TTL 30d  (business-key duplicate)
```

Capacity: PAY_PER_REQUEST (bursty Tuesday-morning arrival).
Provisioning: Day 5 Lab 1 step 1 creates this table.

## 7. IAM scoping

Pipeline execution role: `accelya-pipeline-role-<learner>`. Read raw/, write
validated/, write quarantine/. No PII access (KMS key excluded by boundary).

```json
{
  "Statement": [
    {
      "Sid": "RawListByPrefix",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::accelya-airline-data-ap-south-1",
      "Condition": {
        "StringLike": { "s3:prefix": ["raw/", "raw/*"] }
      }
    },
    {
      "Sid": "RawReadOnly",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::accelya-airline-data-ap-south-1/raw/*"
    },
    {
      "Sid": "ValidatedAndQuarantineWriteScoped",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": [
        "arn:aws:s3:::accelya-airline-data-ap-south-1/validated/${LEARNER}/*",
        "arn:aws:s3:::accelya-airline-data-ap-south-1/quarantine/${LEARNER}/*"
      ]
    },
    {
      "Sid": "IdempotencyDynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem", "dynamodb:GetItem"],
      "Resource": "arn:aws:dynamodb:ap-south-1:*:table/idempotency_keys_${LEARNER}"
    }
  ]
}
```

No `s3:*`, no `Resource:"*"`. ListBucket scoped via Condition.s3:prefix.
ListBucket allows `raw/` (literal prefix) AND `raw/*` (any sub-prefix).

## 8. Cost guardrails

- **Bedrock**: 0 calls in main pipeline (Bedrock is design-time only; not row-level).
- **Lambda**: 4 functions (chunker + validator + lander + dlq_replayer). Within 10-function cap.
- **DynamoDB**: PAY_PER_REQUEST avoids idle cost; TTL keeps table size bounded.
- **S3**: lifecycle policy on quarantine/ (30-day expiry); validated/ → IA after 30d, expire after 2y.
- **CloudWatch**: structured JSON logs (no `print()`); EMF metrics emit only on row-level events (sampled).

Approximate weekly cost per learner: <$1 in this configuration. Sandbox-compatible.

---

## HITL self-review (for trainer reference)

| Dim | Score | Evidence |
|---|---|---|
| Correctness | 3 | All four zones present; six failure modes mapped; idempotency complete |
| Security | 3 | IAM named verbs; Conditions on ListBucket; no wildcards |
| Observability | 3 | correlation_id strategy implied via validator handler reference; per-failure log lines |
| Scalability | 3 | Chunker handles 80MB; Map concurrency 4; idempotency table on-demand |
| Cost | 3 | All sandbox caps respected; no Bedrock in pipeline; lifecycle policies |
| **TOTAL** | **15/15** | PASS — reference standard for cohort scoring |

---

*Reference design. Learners produce their own version; this exists for trainer calibration and as a worked example for Lab 1 debrief.*
