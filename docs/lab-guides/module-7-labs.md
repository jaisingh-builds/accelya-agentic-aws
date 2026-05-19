# Module 7 — Lab Guides (Standalone Reference)

> The Day 7 deck has these labs on slides 22-30; this file is your standalone reference.

---

## Day 7 prerequisites

```bash
cd accelya-agentic-aws
git checkout main && git pull --ff-only
git checkout -b module-7-<your-name>

export LEARNER=<your-name>
export AWS_REGION=ap-south-1
export BUCKET=accelya-airline-data-ap-south-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

Confirm Day 6 artefacts are alive:

```bash
aws glue get-database --name accelya_curated_$LEARNER --region $AWS_REGION \
  --query 'Database.Name' --output text
aws lambda get-function --function-name accelya-etl-json-to-parquet-$LEARNER \
  --region $AWS_REGION --query 'Configuration.State' --output text
```

Confirm `.windsurfrules` v3 is at repo root (today promotes to v4):

```bash
head -2 .windsurfrules    # should reference v3 + CATALOG CONTEXT
```

Close all Cascade chats — `.windsurfrules` v4 pickup test is in Lab 2.

---

## Lab 1 — Provision 2-shard Kinesis stream + IAM + idempotency table (45 min, PAIRS)

**Deliverable:** `scripts/provision_m7_stream.sh` runs clean; `prompts/v10_stream.txt` committed; `/reviews/m7-provision-evidence.md` with `describe-stream` + `describe-table` outputs; MR opened.

### Step 1 — Promote `.windsurfrules` v3 → v4

```bash
diff .windsurfrules docs/.windsurfrules-v4.template | head -40

cp docs/.windsurfrules-v4.template .windsurfrules

git add .windsurfrules
git commit -m "module-7: promote .windsurfrules v3 → v4 (STREAM CONTEXT)"
```

> **What's new in v4:** a `## STREAM CONTEXT` block between `## BATCH CONTEXT` and `## CATALOG CONTEXT`. Stream name, shard count, the two-tier PK strategy, ESM config with `ReportBatchItemFailures`, idempotency table contract, producer/consumer rules. Cascade reads this on every prompt today.

### Step 2 — Pull the 10-layer prompt + run the provision script

```bash
# Confirm the prompt template is present
ls prompts/v10_stream.txt

# Run the provision script
bash scripts/provision_m7_stream.sh $LEARNER
```

The script creates:
1. **Kinesis stream** `accelya-bookings-stream-<learner>` (2 shards, 24h retention)
2. **IAM role** `accelya-stream-role-<learner>` (Kinesis + DDB + S3-quarantine + CW)
3. **DynamoDB table** `stream_seen_keys_<learner>` (TTL `ENABLED` on `ttl`, 7 days)

Idempotent — safe to re-run.

### Step 3 — Verify the stream

```bash
aws kinesis describe-stream --stream-name accelya-bookings-stream-$LEARNER \
  --region $AWS_REGION \
  --query 'StreamDescription.[StreamStatus,length(Shards),RetentionPeriodHours]' \
  --output table
# Expected: ACTIVE / 2 / 24

# Save evidence
mkdir -p reviews
aws kinesis describe-stream --stream-name accelya-bookings-stream-$LEARNER \
  --region $AWS_REGION > /tmp/m7-describe-stream.json
```

### Step 4 — Verify IAM role + DynamoDB table

```bash
aws iam get-role --role-name accelya-stream-role-$LEARNER \
  --query 'Role.[RoleName,Arn]' --output table

aws iam list-role-policies --role-name accelya-stream-role-$LEARNER \
  --query 'PolicyNames' --output text
# Expected: M7StreamPolicy

aws dynamodb describe-table --table-name stream_seen_keys_$LEARNER \
  --region $AWS_REGION \
  --query 'Table.[TableName,TableStatus]' --output table
# Expected: ACTIVE

aws dynamodb describe-time-to-live --table-name stream_seen_keys_$LEARNER \
  --region $AWS_REGION \
  --query 'TimeToLiveDescription.[TimeToLiveStatus,AttributeName]' --output table
# Expected: ENABLED / ttl
```

### Step 5 — Smoke test PutRecord / GetRecords

```bash
# Encode a tiny payload
DATA=$(printf '{"smoke":true,"pk":"AI:2026-05-09"}' | base64)

# Put one record on shardId-000000000000 (PK 'AI:2026-05-09' hashes there)
aws kinesis put-record \
  --stream-name accelya-bookings-stream-$LEARNER \
  --partition-key 'AI:2026-05-09' \
  --data "$DATA" \
  --region $AWS_REGION

# Get a TRIM_HORIZON iterator for shard 0
ITER=$(aws kinesis get-shard-iterator \
  --stream-name accelya-bookings-stream-$LEARNER \
  --shard-id shardId-000000000000 \
  --shard-iterator-type TRIM_HORIZON \
  --region $AWS_REGION \
  --query ShardIterator --output text)

# Read records (base64-encoded data field)
aws kinesis get-records --shard-iterator "$ITER" --region $AWS_REGION \
  --query 'Records[].{seq:SequenceNumber,pk:PartitionKey,data:Data}' --output table
```

Expected: 1 record, with `data` showing your base64 payload (or a Kinesis-encoded variant).

### Step 6 — Capture evidence + commit

```bash
cat > reviews/m7-provision-evidence.md <<'EOF'
# M7 Lab 1 — Provisioning Evidence

## Stream
EOF
aws kinesis describe-stream --stream-name accelya-bookings-stream-$LEARNER --region $AWS_REGION \
  --query 'StreamDescription.[StreamStatus,length(Shards),RetentionPeriodHours]' --output table \
  >> reviews/m7-provision-evidence.md

cat >> reviews/m7-provision-evidence.md <<'EOF'

## IAM role
EOF
aws iam get-role --role-name accelya-stream-role-$LEARNER \
  --query 'Role.[RoleName,Arn]' --output table >> reviews/m7-provision-evidence.md

cat >> reviews/m7-provision-evidence.md <<'EOF'

## DynamoDB table (TTL Enabled on 'ttl')
EOF
aws dynamodb describe-time-to-live --table-name stream_seen_keys_$LEARNER --region $AWS_REGION \
  --output table >> reviews/m7-provision-evidence.md

git add scripts/provision_m7_stream.sh prompts/v10_stream.txt reviews/m7-provision-evidence.md
git commit -m "module-7: provision Kinesis + IAM + DDB (Lab 1)"
git push -u origin module-7-$LEARNER
```

### Lab 1 common gotchas

- **Shard count 1** — default for `create-stream` is 1. Verify the provision script passed `--shard-count 2`.
- **TTL not enabled** — `update-time-to-live` is a *separate* CLI call. Re-run the provision script if `describe-time-to-live` shows `DISABLED`.
- **IAM denial on smoke test** — propagation delay. Wait 30 s and re-try.
- **Cross-region accident** — always pass `--region ap-south-1`. Default region from `~/.aws/config` may differ.

---

## Lab 2 — Producer contract design (paper exercise, 45 min, SOLO)

**Deliverable:** `/design/m7-producer-contract.md` with 6 sections + ASCII flow diagram; `/reviews/HITL_REVIEW-m7-producer.md` scored 6-dim ≥14/18; MR shows 2 commits.

**Reference:** `design/m7-producer-contract.example.md` — the trainer's worked example. Use the structure, write your own content.

### Step 1 — Author the design doc with Cascade

Open a **fresh** Cascade chat. Prompt:

```
@cascade Read .windsurfrules v4. Using STREAM CONTEXT, author
design/m7-producer-contract.md with the 6 sections from prompts/v10_stream.txt
layer 9 (TASK). Each section ≤200 words. Include an ASCII flow diagram in
section 3. No code beyond the PK formula and the EMF metric log line shape.
```

Expected: ~1200-word markdown file with input/output/side-effects/retry/metrics/failure-handling sections.

### Step 2 — Verify the PK formula

The PK must be:

```python
pk = f"{event['airline_code']}:{event['booking_date']}"
```

NOT:
- `pk = str(uuid.uuid4())` (random — loses ordering)
- `pk = "cancellation"` (static — hot shard)
- `pk = event['airline_code']` (low cardinality — skewed)

### Step 3 — Verify the retry policy

Must catch `ProvisionedThroughputExceededException`, backoff+jitter, cap at 5 retries. Re-submit only failed records.

### Step 4 — Pickup test for `.windsurfrules` v4

Open ANOTHER fresh Cascade chat. Prompt:

```
Scaffold a Lambda producer for cancellation events to the bookings stream.
```

Check Cascade's output for these four signals (all four must pass):
1. ✅ References `accelya-bookings-stream-<learner>` (NOT some other name)
2. ✅ PK from `airline_code:booking_date` (NOT random or static)
3. ✅ Uses `put_records` (NOT `put_record` in a loop)
4. ✅ Catches `ProvisionedThroughputExceededException`
5. ✅ Emits EMF metrics

If any signal fails — `.windsurfrules` v4 didn't load cleanly. Verify with `head -10 .windsurfrules` that the STREAM CONTEXT block is present.

### Step 5 — Pair HITL review (6 dimensions)

```bash
mkdir -p reviews
cat > reviews/HITL_REVIEW-m7-producer.md <<'EOF'
# HITL Review — m7-producer-contract.md

Reviewer: <pair partner name>

| Dim | Score 0-3 | Evidence |
|---|---|---|
| Correctness    | _/3 | All 5 event types accommodated; envelope complete |
| Safety         | _/3 | Pre-submit validation; no PII in error_message |
| Idempotency    | _/3 | Producer stateless; consumer owns idempotency |
| Observability  | _/3 | EMF metrics + corr_id; alarm hook for Day 10 |
| Cost           | _/3 | PutRecords bulk; retry cap 5; no put_record loop |
| Per-PK Order   | _/3 | PK deterministic; cancel→refund same-PNR analysis |

**Total: _/18. Pass at ≥14/18 AND every dim ≥2/3.**

## Notes
- ...
EOF
```

### Step 6 — Commit

```bash
git add design/m7-producer-contract.md reviews/HITL_REVIEW-m7-producer.md
git commit -m "module-7: producer contract design + HITL review (Lab 2)"
git push
```

### Lab 2 common gotchas

- **Cascade returns 3000-word design** — first drafts always too long. Reply: *"Tighten each section to 200 words max."*
- **Cascade uses `put_record` in a loop** — STREAM CONTEXT block didn't load. Re-check `.windsurfrules` head; close + reopen chat.
- **Cascade uses random `uuid4` for PK** — same root cause. STREAM CONTEXT lists this as Forbidden.
- **`Per-PK Order` dim graded 0/3** — your PK strategy doesn't preserve order. Re-state: same PNR's cancel+refund must land on same shard.

---

## Lab 3 — Hot-shard demo (3 PK strategies, 10K events, 45 min, PAIRS)

**Deliverable:** `/reviews/m7-hot-shard-evidence.md` with per-shard `IncomingBytes` for two PK strategies + ordering test result + production recommendation; MR shows 3 commits.

### Step 1 — Generate 10K synthetic events

```bash
python3 -m scripts.gen_m7_events \
  --count 10000 \
  --airlines AI,EK,LH,SQ \
  --date-range 2026-05-01..2026-05-10 \
  --out /tmp/m7-events-10k.jsonl

# Verify
wc -l /tmp/m7-events-10k.jsonl    # 10000
head -1 /tmp/m7-events-10k.jsonl | python3 -m json.tool | head -15
```

### Step 2 — Strategy A: random PK (booking_id UUID)

```bash
# Helper: push with given PK strategy
push_strategy() {
  local STRATEGY=$1 FILE=$2 START_NOTE=$3
  echo ""
  echo "═══ Strategy $STRATEGY pushing 10K events ═══"
  echo "Started at: $(date -u +%H:%M:%S)"

  while IFS= read -r line; do
    case "$STRATEGY" in
      A) PK=$(echo "$line" | jq -r .event_id) ;;
      B) PK=$(echo "$line" | jq -r '.airline_code + ":" + .booking_date') ;;
    esac
    DATA=$(echo -n "$line" | base64)
    aws kinesis put-record \
      --stream-name accelya-bookings-stream-$LEARNER \
      --partition-key "$PK" \
      --data "$DATA" \
      --region $AWS_REGION \
      --no-cli-pager >/dev/null 2>&1
  done < "$FILE"

  echo "Finished at: $(date -u +%H:%M:%S)"
}

push_strategy A /tmp/m7-events-10k.jsonl
```

> **Note:** Pushing 10K events one-at-a-time takes ~15-20 minutes via `put-record`. For production you'd use `put-records` batch (≤500 per call). For pedagogy here, one-at-a-time is fine — and gives the trainer time to walk the room.

**While Strategy A runs, narrate:** *"Random PK means every event hashes to a uniformly-distributed shard. Watch CloudWatch in 3 minutes — both shards will show roughly equal `IncomingBytes`. But the ordering test in Step 4 will fail."*

After completion, wait **3 minutes** for CloudWatch metric publishing delay.

### Step 3 — Capture Strategy A per-shard distribution

```bash
START_TIME=$(date -u -v-5M +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u --date='5 minutes ago' +%Y-%m-%dT%H:%M:%S)
END_TIME=$(date -u +%Y-%m-%dT%H:%M:%S)

for SHARD in 0 1; do
  echo "--- shardId-00000000000$SHARD ---"
  aws cloudwatch get-metric-statistics \
    --namespace AWS/Kinesis \
    --metric-name IncomingBytes \
    --dimensions Name=StreamName,Value=accelya-bookings-stream-$LEARNER \
                 Name=ShardId,Value=shardId-00000000000$SHARD \
    --start-time $START_TIME --end-time $END_TIME --period 60 \
    --statistics Sum --region $AWS_REGION \
    --query 'Datapoints[].[Timestamp,Sum]' --output table
done
```

Save the totals to `/tmp/m7-strategy-a-shard-bytes.json`:

```bash
echo "{}" > /tmp/m7-strategy-a-shard-bytes.json
for SHARD in 0 1; do
  TOTAL=$(aws cloudwatch get-metric-statistics \
    --namespace AWS/Kinesis --metric-name IncomingBytes \
    --dimensions Name=StreamName,Value=accelya-bookings-stream-$LEARNER \
                 Name=ShardId,Value=shardId-00000000000$SHARD \
    --start-time $START_TIME --end-time $END_TIME --period 300 \
    --statistics Sum --region $AWS_REGION \
    --query 'Datapoints[0].Sum' --output text)
  echo "  shard $SHARD: $TOTAL bytes"
  jq ".\"shard_$SHARD\" = $TOTAL" /tmp/m7-strategy-a-shard-bytes.json > /tmp/sa-tmp.json
  mv /tmp/sa-tmp.json /tmp/m7-strategy-a-shard-bytes.json
done
cat /tmp/m7-strategy-a-shard-bytes.json
```

### Step 4 — Strategy B: composite PK (airline_code + booking_date)

```bash
push_strategy B /tmp/m7-events-10k.jsonl
```

Wait 3 minutes, then capture Strategy B distribution (same pattern as step 3, save to `/tmp/m7-strategy-b-shard-bytes.json`).

### Step 5 — Ordering test (same-PK cancel→refund chain)

```bash
# Cancel event
CXL_DATA=$(printf '{"event_id":"CXL-T1","event_type":"cancellation","airline_code":"AI","booking_date":"2026-05-09","pnr":"TEST01","payload":{"pnr":"TEST01","cancel_reason_code":"PAX"}}' | base64)
CXL_RESP=$(aws kinesis put-record \
  --stream-name accelya-bookings-stream-$LEARNER \
  --partition-key 'AI:2026-05-09' \
  --data "$CXL_DATA" \
  --region $AWS_REGION \
  --output json)
CXL_SEQ=$(echo "$CXL_RESP" | jq -r .SequenceNumber)
CXL_SHARD=$(echo "$CXL_RESP" | jq -r .ShardId)
echo "Cancel:  shard=$CXL_SHARD  seq=$CXL_SEQ"

# Refund event (strict order: SequenceNumberForOrdering=<prev>)
REF_DATA=$(printf '{"event_id":"REF-T1","event_type":"refund","airline_code":"AI","booking_date":"2026-05-09","pnr":"TEST01","payload":{"pnr":"TEST01","original_cancel_event_id":"CXL-T1","refund_amount":2845.0,"currency":"INR"}}' | base64)
REF_RESP=$(aws kinesis put-record \
  --stream-name accelya-bookings-stream-$LEARNER \
  --partition-key 'AI:2026-05-09' \
  --data "$REF_DATA" \
  --sequence-number-for-ordering "$CXL_SEQ" \
  --region $AWS_REGION \
  --output json)
REF_SEQ=$(echo "$REF_RESP" | jq -r .SequenceNumber)
REF_SHARD=$(echo "$REF_RESP" | jq -r .ShardId)
echo "Refund:  shard=$REF_SHARD  seq=$REF_SEQ"

# Verify same shard + refund seq > cancel seq
if [[ "$CXL_SHARD" == "$REF_SHARD" ]] && [[ "$REF_SEQ" > "$CXL_SEQ" ]]; then
  echo "✓ Ordering preserved: same shard, refund seq > cancel seq"
else
  echo "✗ Ordering broken — same_shard=$([[ "$CXL_SHARD" == "$REF_SHARD" ]] && echo yes || echo no)"
fi
```

Expected: same shard, refund's sequence_number lexicographically > cancel's.

### Step 6 — Document the evidence + commit

```bash
cat > reviews/m7-hot-shard-evidence.md <<EOF
# M7 Lab 3 — Hot-Shard Evidence

## Strategy A (random PK = event_id UUID)

\`\`\`json
$(cat /tmp/m7-strategy-a-shard-bytes.json)
\`\`\`

Observation: distribution is roughly even (~50:50). Random PK distributes
well at scale, but loses per-PNR ordering for cancel-refund chains.

## Strategy B (composite PK = airline_code:booking_date)

\`\`\`json
$(cat /tmp/m7-strategy-b-shard-bytes.json)
\`\`\`

Observation: distribution within ≤55:45 split. With 4 airlines × 10 dates =
40 unique PKs, some skew is expected (a few PKs carry more events).

## Ordering test

- Cancel:  shard=$CXL_SHARD  seq=$CXL_SEQ
- Refund:  shard=$REF_SHARD  seq=$REF_SEQ
- Same shard: $([[ "$CXL_SHARD" == "$REF_SHARD" ]] && echo "✓ YES" || echo "✗ NO")
- Refund seq > Cancel seq: $([[ "$REF_SEQ" > "$CXL_SEQ" ]] && echo "✓ YES" || echo "✗ NO")

## Production recommendation

**Use Strategy B** (composite \`airline_code:booking_date\`) for the
bookings stream. At lab scale, distribution is acceptable (~55:45);
at production scale with hash-bucket extension
\`{airline}:{date}:{bucket_hash(pnr) % 8}\` distribution becomes uniform
while preserving per-PNR ordering.
EOF

git add reviews/m7-hot-shard-evidence.md
git commit -m "module-7: hot-shard evidence + ordering test (Lab 3)"
git push
```

### Lab 3 common gotchas

- **CloudWatch metrics flat for 3 minutes** — propagation delay. Wait. Don't restart.
- **Strategy A and B both show 50:50 split** — possibly the test data is too small. 10K events × tiny payload = both shards likely under quota. The teaching point is observable PK predictability, not ratio.
- **Ordering test on different shards** — both PKs must be `'AI:2026-05-09'`. If you typed different values, they hash to different shards and the test is meaningless.
- **`SequenceNumberForOrdering` not passed on refund** — strict ordering requires this flag. Without it, refund could land out of order.

---

## End-of-module cleanup

```bash
bash scripts/cleanup_module7.sh $LEARNER
```

**No deletions** — Day 7 is design-only and all provisioned infrastructure (stream, role, table) stays alive for Day 8. The cleanup script verifies all three are still ACTIVE and TTL is ENABLED.

---

## Day 7 in numbers

| Metric | Value |
|---|---|
| New Lambdas deployed today | **0** |
| Cumulative Lambda count | 6 of 10 (unchanged) |
| Kinesis streams | 1 (2 shards, 24h retention) |
| IAM roles created | 1 |
| DynamoDB tables created | 1 |
| Synthetic events tested | 10,000 |
| `.windsurfrules` version | v4 |
| HITL dimensions | 6 + new Per-PK Order (lab-local for Lab 2) |
| AWS Bedrock invocations | ~0 today (cumulative ~10 of 50) |
| Glue DPU-h | 0 today (cumulative ≤1 of 6) |
| MR commits | 3 |

---

## What's coming on Day 8

Module 8 — **Agentic Real-Time Processing**. Cascade authors:
- Producer Lambda (uses today's PK strategy + EMF retry pattern)
- THIN consumer Lambda (claim sequence_number → `StartExecution` on inference SFN → ACK)
- bedrock-enrich Lambda (sampled enrichment, every Nth event)
- Inference-pipeline state machine

`.windsurfrules` v4 → **v5** with `STATE CONTEXT` block (11th prompt layer).

Bring tomorrow:
- Today's stream + role + idempotency table (all alive)
- `design/m7-producer-contract.md` (Day 8 builds from this design)
- `.windsurfrules` v4 (Day 8 promotes to v5)

---

*See `Day7_Module7_Streaming_Architecture.pptx` slides 22-30 for the deck's visual treatment.*
