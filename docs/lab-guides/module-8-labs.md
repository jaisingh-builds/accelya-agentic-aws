# Module 8 — Lab Guides (Standalone Reference)

> The Day 8 deck has these labs on slides 20-28; this file is your standalone reference.

---

## Day 8 prerequisites

```bash
cd accelya-agentic-aws
git checkout main && git pull --ff-only
git checkout -b module-8-<your-name>

export LEARNER=<your-name>
export AWS_REGION=ap-south-1
export BUCKET=accelya-airline-data-ap-south-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

Confirm Day 7 artefacts:

```bash
aws kinesis describe-stream --stream-name accelya-bookings-stream-$LEARNER \
  --region $AWS_REGION --query 'StreamDescription.[StreamStatus,length(Shards)]'
# Expected: ACTIVE, 2

aws iam get-role --role-name accelya-stream-role-$LEARNER \
  --query 'Role.[RoleName,Arn]' --output table

aws dynamodb describe-time-to-live --table-name stream_seen_keys_$LEARNER \
  --region $AWS_REGION --query 'TimeToLiveDescription.TimeToLiveStatus'
# Expected: ENABLED

head -2 .windsurfrules    # should reference v4 + STREAM CONTEXT
```

Close all Cascade chats. STATE CONTEXT pickup test is in Lab 1.

---

## Lab 1 — Cascade-author 3 Lambdas + state machine (45 min, PAIRS)

**Deliverable:** 4 Lambdas Active (count 9/10); `inference-pipeline-<learner>` state machine ACTIVE; `.windsurfrules` v5 + `prompts/v11_stream_state.txt` + `src/common/exceptions.py` (+ `BedrockThrottleError`); `/reviews/HITL_REVIEW-m8-streaming.md` ≥ 17/21.

### Step 1 — Promote `.windsurfrules` v4 → v5

```bash
diff .windsurfrules docs/.windsurfrules-v5.template | head -50

cp docs/.windsurfrules-v5.template .windsurfrules

# Copy the 11-layer prompt
cp prompts/v10_stream.txt prompts/v11_stream_state.txt
# (then manually splice the STATE CONTEXT block reference per .windsurfrules-v5)
# OR just use the canonical version:
# (the prompts/v11_stream_state.txt is already in the repo — verify it matches)

git add .windsurfrules prompts/v11_stream_state.txt
git commit -m "module-8: promote .windsurfrules v4 → v5 (STATE CONTEXT)"
```

> **What's new in v5:** `## STATE CONTEXT` block between STREAM CONTEXT and CATALOG CONTEXT. Defines the THIN consumer 4-stage flow, sampling-lives-in-bedrock-enrich rule, hard cost guard env vars, and the deterministic-execution-name pattern.

### Step 2 — Cascade scaffolds 4 handlers + ASL

Open a **fresh** Cascade chat. Prompt:

```
@cascade Read .windsurfrules v5 + prompts/v11_stream_state.txt. Using
STATE CONTEXT, scaffold these four Lambdas + the state machine:

  src/producer/handler.py            — bulk PutRecords with PNR-bucketed PK
  src/consumer/handler.py            — THIN; 4 stages; deterministic exec_name
  src/bedrock_enrich/handler.py      — SFN Task; SAMPLE_RATE; HARD COST GUARD
  src/persist_enriched/handler.py    — SFN Task; gzip + Hive-style S3 key
  infra/inference-pipeline.asl.json  — BedrockEnrich → Persist + Quarantine Catch

Plus extend src/common/exceptions.py with BedrockThrottleError (subclass of
PipelineError, quarantine_reason='bedrock_throttle').

Plus tests in tests/test_producer.py, test_consumer.py, test_bedrock_enrich.py,
test_persist_enriched.py.
```

**Reference handlers** (compare against Cascade's output):
- `src/producer/handler.py` (committed)
- `src/consumer/handler.py` (committed)
- `src/bedrock_enrich/handler.py` (committed)
- `src/persist_enriched/handler.py` (committed)
- `infra/inference-pipeline.asl.json` (committed)

**Common first-draft issues to push back on:**
- Cascade writes inline Bedrock in consumer → STATE CONTEXT forbids; redirect to bedrock-enrich.
- Cascade uses `uuid.uuid4()` for exec_name → STATE CONTEXT mandates `f"enrich-{event_id}"`.
- Cascade returns all failures → STATE CONTEXT mandates oldest-only.
- Cascade uses `random.random()` for sampling → STATE CONTEXT forbids; redirect to MD5.

### Step 3 — Deploy 4 Lambdas + DLQ

```bash
bash scripts/deploy_m8_lambdas.sh $LEARNER
```

The script:
1. Verifies Day-7 stream + IAM role + idempotency table alive
2. Creates SQS DLQ `stream-dlq-<learner>`
3. Extends `accelya-stream-role-<learner>` with `states:StartExecution`, `bedrock:InvokeModel`, `cloudwatch:GetMetricStatistics`, `dynamodb:UpdateItem`, `s3:PutObject`, `sqs:SendMessage`
4. Deploys all 4 Lambdas (producer, bedrock-enrich, persist-enriched, consumer)
5. Prints the next-step `aws lambda create-event-source-mapping` command for Lab 2

### Step 4 — Deploy state machine

```bash
bash scripts/deploy_m8_state_machine.sh $LEARNER
```

This:
1. Extends the SFN role with permission to invoke M8 Lambdas
2. Renders `inference-pipeline.asl.json` via envsubst
3. Validates the ASL
4. Creates/updates the state machine `inference-pipeline-<learner>`
5. Patches the consumer Lambda's `SM_ARN` env var with the new ARN

Verify:

```bash
aws stepfunctions list-state-machines --region $AWS_REGION \
  --query "stateMachines[?name=='inference-pipeline-$LEARNER'].name" --output text
# Expected: inference-pipeline-<learner>

aws lambda get-function-configuration --function-name accelya-consumer-$LEARNER \
  --region $AWS_REGION --query 'Environment.Variables.SM_ARN' --output text
# Expected: arn:aws:states:...:stateMachine:inference-pipeline-<learner>
```

### Step 5 — Pickup test for `.windsurfrules` v5

Open ANOTHER fresh Cascade chat. Prompt:

```
Write me a thin Kinesis consumer Lambda for the bookings stream.
```

Check Cascade's output for these signals (all should pass):
1. ✅ `itemIdentifier = sequence_number` (NOT messageId)
2. ✅ PK uses `stream#<name>#<shard>#<seq>` pattern
3. ✅ Reports only oldest failure (loop + min(seq_num) pattern)
4. ✅ No inline Bedrock import
5. ✅ Deterministic exec_name: `f"enrich-{event_id}"`

If any signal fails — STATE CONTEXT didn't load. Re-check `.windsurfrules` v5.

### Step 6 — Pair-HITL on 7 dimensions

```bash
cat > reviews/HITL_REVIEW-m8-streaming.md <<'EOF'
# HITL Review — m8 streaming (Lab 1 + Lab 2 deliverables)

Reviewer: <pair partner name>

| Dim | Score 0-3 | Evidence |
|---|---|---|
| Correctness        | _/3 | All 4 stages in order; deterministic exec_name |
| Safety             | _/3 | Pre-submit validation in producer; no PII in logs |
| Idempotency        | _/3 | Claim BEFORE side-effect; ExecutionAlreadyExists caught |
| Observability      | _/3 | EMF per Lambda with distinct dimensions |
| Cost               | _/3 | Sampling in bedrock-enrich + hard cost guard env vars |
| Schema Discipline  | _/3 | BedrockThrottleError added to PipelineError ladder |
| Per-PK Ordering    | _/3 | Producer PK formula deterministic; consumer per-shard |

**Total: _/21. Pass at ≥17/21 AND every dim ≥2/3.**

## Notes
- ...
EOF
```

Commit:

```bash
git add src/producer/ src/consumer/ src/bedrock_enrich/ src/persist_enriched/ \
        src/common/exceptions.py \
        infra/inference-pipeline.asl.json \
        scripts/deploy_m8_lambdas.sh scripts/deploy_m8_state_machine.sh \
        reviews/HITL_REVIEW-m8-streaming.md \
        tests/test_*.py
git commit -m "module-8: 4 streaming Lambdas + state machine + HITL (Lab 1)"
git push -u origin module-8-$LEARNER
```

### Lab 1 common gotchas

- **Cascade overwrites Day-7 design doc** — protect `design/m7-producer-contract.md`; Cascade should READ but not write it.
- **Bedrock IAM denial** — `bedrock:InvokeModel` requires `Resource: "*"` (Bedrock doesn't yet support fine-grained model ARNs in all regions). `deploy_m8_lambdas.sh` handles this.
- **`SM_ARN` placeholder mismatch** — `deploy_m8_lambdas.sh` writes a placeholder; `deploy_m8_state_machine.sh` overwrites it with the real ARN. If learners skip the second script, the consumer's `start_execution` fails with `StateMachineDoesNotExist`.
- **HITL score 16/21** — one or two dims below 2/3. Re-check Per-PK Ordering (most-failed) — producer must hash on `pnr` not random.

---

## Lab 2 — Wire ESM + observe partial-batch retry (45 min, SOLO)

**Deliverable:** ESM Active with all 6 explicit flags; 8 events in enriched/, 2 in quarantine/; `/reviews/m8-partial-batch-evidence.md` with full trace.

### Step 1 — Wire the ESM

```bash
STREAM_ARN=$(aws kinesis describe-stream --stream-name accelya-bookings-stream-$LEARNER \
  --region $AWS_REGION --query 'StreamDescription.StreamARN' --output text)
DLQ_URL=$(aws sqs get-queue-url --queue-name stream-dlq-$LEARNER \
  --region $AWS_REGION --query QueueUrl --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url $DLQ_URL \
  --attribute-names QueueArn --region $AWS_REGION \
  --query 'Attributes.QueueArn' --output text)

aws lambda create-event-source-mapping \
  --function-name accelya-consumer-$LEARNER \
  --event-source-arn $STREAM_ARN \
  --batch-size 100 \
  --maximum-batching-window-in-seconds 5 \
  --parallelization-factor 1 \
  --maximum-retry-attempts 3 \
  --maximum-record-age-in-seconds 3600 \
  --bisect-batch-on-function-error \
  --function-response-types ReportBatchItemFailures \
  --starting-position LATEST \
  --destination-config "{\"OnFailure\":{\"Destination\":\"$DLQ_ARN\"}}" \
  --region $AWS_REGION
```

Verify all 6 flags:

```bash
aws lambda list-event-source-mappings --function-name accelya-consumer-$LEARNER \
  --region $AWS_REGION \
  --query 'EventSourceMappings[].[State,BatchSize,MaximumRetryAttempts,MaximumRecordAgeInSeconds,BisectBatchOnFunctionError,FunctionResponseTypes]' \
  --output table
# Expected: Enabled / 100 / 3 / 3600 / true / [ReportBatchItemFailures]
```

Wait for `State=Enabled` (1-2 minutes).

### Step 2 — Generate test batch (8 valid + 2 poison)

```bash
python3 -m scripts.gen_m8_test_batch --rows 10 --poison 2 --out /tmp/m8-test-batch.json
```

### Step 3 — Invoke producer

```bash
aws lambda invoke \
  --function-name accelya-producer-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/m8-test-batch.json \
  --region $AWS_REGION \
  /tmp/m8-producer-out.json

cat /tmp/m8-producer-out.json | python3 -m json.tool
# Expected: submitted_count=8, failed_count=2 (the 2 poison records rejected pre-submit)
```

### Step 4 — Trace via CloudWatch Logs Insights

```bash
QUERY='fields @timestamp, event, corr_id, stream_pk
       | filter event in ["record_duplicate","handoff_succeeded","handoff_already_exists","row_quarantined","handoff_failed_transient"]
       | sort @timestamp asc
       | limit 50'
START=$(($(date +%s) - 300))
END=$(date +%s)

QID=$(aws logs start-query \
  --log-group-name /aws/lambda/accelya-consumer-$LEARNER \
  --start-time $START --end-time $END \
  --query-string "$QUERY" \
  --region $AWS_REGION --query queryId --output text)

# Wait then fetch
sleep 5
aws logs get-query-results --query-id $QID --region $AWS_REGION \
  --query 'results[].[field[].value]' --output text
```

Expected: 8 `handoff_succeeded` events.

### Step 5 — Verify S3 + DynamoDB

```bash
echo "--- enriched/ contents (target: 8 files for 8 valid events) ---"
aws s3 ls s3://$BUCKET/enriched/$LEARNER/ --recursive --region $AWS_REGION | head -15

echo "--- quarantine/stream_invalid/ contents (target: 0; producer rejected the poison pre-submit) ---"
aws s3 ls s3://$BUCKET/quarantine/$LEARNER/stream_invalid/ --recursive --region $AWS_REGION | head -10

echo "--- stream_seen_keys claims (target: 8 stream# PKs with status=COMPLETED) ---"
aws dynamodb scan --table-name stream_seen_keys_$LEARNER --region $AWS_REGION \
  --filter-expression "begins_with(pk, :p)" \
  --expression-attribute-values '{":p":{"S":"stream#"}}' \
  --query 'Items[].[pk.S,status.S]' --output table
```

### Step 6 — Re-trigger test (idempotency proof)

```bash
# Re-invoke producer with the SAME payload
aws lambda invoke \
  --function-name accelya-producer-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/m8-test-batch.json \
  --region $AWS_REGION \
  /tmp/m8-producer-out2.json

# Wait + check for ExecutionAlreadyExists in consumer logs
sleep 15
aws logs tail /aws/lambda/accelya-consumer-$LEARNER \
  --since 1m --region $AWS_REGION 2>&1 | grep -E "handoff_already_exists|record_duplicate" | head -10
```

Document everything in `/reviews/m8-partial-batch-evidence.md`:

```bash
cat > reviews/m8-partial-batch-evidence.md <<EOF
# M8 Lab 2 — Partial-Batch Evidence

## ESM config (all 6 flags explicit)
- BatchSize: 100
- MaximumBatchingWindowInSeconds: 5
- ParallelizationFactor: 1
- MaximumRetryAttempts: 3
- MaximumRecordAgeInSeconds: 3600
- BisectBatchOnFunctionError: true
- FunctionResponseTypes: [ReportBatchItemFailures]
- StartingPosition: LATEST
- OnFailure: stream-dlq-$LEARNER

## Producer first run
submitted_count: 8, failed_count: 2 (validation pre-submit)

## Consumer trace (CloudWatch Logs Insights)
- 8 handoff_succeeded events
- 0 record_failures
- 8 stream#... PKs in stream_seen_keys with status=COMPLETED

## S3 outcomes
- enriched/$LEARNER/: 8 files (one per valid event)
- quarantine/$LEARNER/stream_invalid/: 0 (poison rejected by producer pre-submit)

## Re-trigger idempotency
After re-invoking producer with same payload:
- Producer submitted 8 more (new sequence numbers from Kinesis perspective)
- Consumer logged handoff_already_exists (ExecutionAlreadyExists from SFN)
- enriched/ count: still 8 (no duplicate writes)
EOF
```

Commit:

```bash
git add reviews/m8-partial-batch-evidence.md
git commit -m "module-8: ESM + partial-batch evidence (Lab 2)"
git push
```

### Lab 2 common gotchas

- **ESM stuck in `Creating`** — Kinesis-Lambda ESM takes 60-90 s to settle. Wait.
- **No `handoff_succeeded` events in logs** — ESM not actually Enabled OR consumer permissions denied. Check `aws lambda list-event-source-mappings --function-name accelya-consumer-$LEARNER`.
- **All 10 records show `record_duplicate`** — your producer is putting events with the same `event_id`, OR the consumer ran twice. Reset by deleting stream_seen_keys PKs and re-invoking.
- **`ExecutionAlreadyExists` on first run** — your consumer is re-firing; check ESM Enabled, then check if `name=f"enrich-{event_id}"` and event_ids are unique.

---

## Lab 3 — Cost A/B (enrich-every vs enrich-sampled) (45 min, PAIRS)

**Deliverable:** Run A (SAMPLE_RATE=1, 25 events) and Run B (SAMPLE_RATE=10, 25 events) capture; ratio ≥ 8×; SAMPLE_RATE reset to 10; `/reviews/m8-enrichment-cost-ab.md`.

### Step 1 — Capture baseline Bedrock metrics

```bash
PROFILE="apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
START=$(date -u -v-5M +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u --date='5 minutes ago' +%Y-%m-%dT%H:%M:%S)
END=$(date -u +%Y-%m-%dT%H:%M:%S)

get_metric() {
  aws cloudwatch get-metric-statistics \
    --namespace AWS/Bedrock --metric-name "$1" \
    --dimensions Name=ModelId,Value=$PROFILE \
    --start-time $START --end-time $END --period 300 \
    --statistics Sum --region $AWS_REGION \
    --query 'Datapoints[0].Sum' --output text 2>/dev/null || echo "0"
}

echo "Baseline (last 5 min):"
echo "  Invocations:      $(get_metric Invocations)"
echo "  InputTokenCount:  $(get_metric InputTokenCount)"
echo "  OutputTokenCount: $(get_metric OutputTokenCount)"
```

### Step 2 — Run A: SAMPLE_RATE=1 (every event)

```bash
CURRENT_ENV=$(aws lambda get-function-configuration \
  --function-name accelya-bedrock-enrich-$LEARNER --region $AWS_REGION \
  --query 'Environment.Variables' --output json)
NEW_ENV=$(echo "$CURRENT_ENV" | python3 -c "
import json, sys
env = json.load(sys.stdin)
env['SAMPLE_RATE'] = '1'
print(json.dumps({'Variables': env}))
")
aws lambda update-function-configuration \
  --function-name accelya-bedrock-enrich-$LEARNER \
  --environment "$NEW_ENV" --region $AWS_REGION >/dev/null
aws lambda wait function-updated-v2 --function-name accelya-bedrock-enrich-$LEARNER --region $AWS_REGION

# Generate + send 25 events
python3 -m scripts.gen_m8_test_batch --rows 25 --poison 0 --out /tmp/m8-25-events.json
aws lambda invoke \
  --function-name accelya-producer-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/m8-25-events.json \
  --region $AWS_REGION /tmp/m8-run-a-producer.json

echo "Run A: events submitted; sleeping 90 s for Bedrock metric publish..."
sleep 90
```

### Step 3 — Capture Run A metrics

```bash
END=$(date -u +%Y-%m-%dT%H:%M:%S)
echo "Run A metrics (5-min window):"
echo "  Invocations:      $(get_metric Invocations)"
echo "  InputTokenCount:  $(get_metric InputTokenCount)"
echo "  OutputTokenCount: $(get_metric OutputTokenCount)"
# Expected: ~25 invocations
```

### Step 4 — Run B: SAMPLE_RATE=10 (1-in-10 sampled)

```bash
NEW_ENV=$(echo "$CURRENT_ENV" | python3 -c "
import json, sys
env = json.load(sys.stdin)
env['SAMPLE_RATE'] = '10'
print(json.dumps({'Variables': env}))
")
aws lambda update-function-configuration \
  --function-name accelya-bedrock-enrich-$LEARNER \
  --environment "$NEW_ENV" --region $AWS_REGION >/dev/null
aws lambda wait function-updated-v2 --function-name accelya-bedrock-enrich-$LEARNER --region $AWS_REGION

# Generate fresh 25 events (different event_ids)
python3 -m scripts.gen_m8_test_batch --rows 25 --poison 0 --out /tmp/m8-25-events-b.json
aws lambda invoke \
  --function-name accelya-producer-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/m8-25-events-b.json \
  --region $AWS_REGION /tmp/m8-run-b-producer.json

echo "Run B: events submitted; sleeping 90 s..."
sleep 90
```

### Step 5 — Capture Run B metrics

```bash
END=$(date -u +%Y-%m-%dT%H:%M:%S)
echo "Run B metrics (5-min window total — includes Run A):"
echo "  Invocations:      $(get_metric Invocations)"
echo "  InputTokenCount:  $(get_metric InputTokenCount)"
echo "  OutputTokenCount: $(get_metric OutputTokenCount)"
# Run B's *delta* should be ~2-3 invocations
```

### Step 6 — Document + reset

```bash
cat > reviews/m8-enrichment-cost-ab.md <<EOF
# M8 Lab 3 — Enrichment Cost A/B Evidence

## Test setup
- 25 events per run
- SAMPLE_RATE toggled on accelya-bedrock-enrich-$LEARNER only

## Run A: SAMPLE_RATE=1 (every event)
- Bedrock Invocations: <fill in from output above, ~25>
- Input tokens: <fill in>
- Output tokens: <fill in>

## Run B: SAMPLE_RATE=10 (1-in-10 sampling)
- Bedrock Invocations: <fill in from delta, ~2-3>
- Input tokens: <fill in>
- Output tokens: <fill in>

## Ratio
- Run A / Run B: ~8-10× cost reduction at lab scale
- At production volume (10K events/min), savings compound: 25K → 2.5K invocations/min

## Production tuning
- <100 events/min: SAMPLE_RATE=1 (every event affordable)
- 100-1,000 events/min: SAMPLE_RATE=10 (balanced)
- >1,000 events/min: SAMPLE_RATE=100 + flag downstream

## Reset
SAMPLE_RATE reset to 10 at end of Lab 3.
EOF

# CRITICAL — reset SAMPLE_RATE to 10
echo "Resetting SAMPLE_RATE=10..."
NEW_ENV=$(echo "$CURRENT_ENV" | python3 -c "
import json, sys
env = json.load(sys.stdin)
env['SAMPLE_RATE'] = '10'
print(json.dumps({'Variables': env}))
")
aws lambda update-function-configuration \
  --function-name accelya-bedrock-enrich-$LEARNER \
  --environment "$NEW_ENV" --region $AWS_REGION >/dev/null

git add reviews/m8-enrichment-cost-ab.md
git commit -m "module-8: cost A/B sampled enrichment evidence (Lab 3)"
git push
```

### Lab 3 common gotchas

- **Bedrock CW metrics still 0** — 30-60 s publishing lag. Wait full 90 s.
- **Forgot to reset SAMPLE_RATE** — the cleanup script enforces it as safety net.
- **Run B shows 25 invocations not 2-3** — `SAMPLE_RATE` update didn't apply; Lambda was still warm with cached env. Force a cold start by adding `--no-wait` and immediately invoking again.
- **Bedrock budget guard fires** — you've used too many cumulative invocations. Check `aws cloudwatch get-metric-statistics --period 86400`. If you're over 38, the guard activates and Run A will show fewer than 25 actual Bedrock calls. Document this in the evidence file as "budget guard fired" rather than a test failure.

---

## End-of-module cleanup

```bash
bash scripts/cleanup_module8.sh $LEARNER
```

The script:
1. Restores `SAMPLE_RATE=10` on bedrock-enrich (if Lab 3 left it lower)
2. Verifies all 4 M8 Lambdas Active + state machine PRESENT + ESM enabled
3. Reports Lambda count (target: 9 of 10) and Bedrock budget burn (target: ~25 of 50)

**No deletions** — Day 9 extends `inference-pipeline-<learner>` with a Parallel SageMaker branch.

---

## Day 8 in numbers

| Metric | Value |
|---|---|
| New Lambdas | 4 (producer, consumer, bedrock-enrich, persist-enriched) |
| Cumulative Lambdas | 9 of 10 (1 reserved for Day 9 predict wrapper) |
| State machines | 1 (`inference-pipeline-<learner>`) |
| ESM event-source-mappings | 1 |
| SQS DLQ | 1 (`stream-dlq-<learner>`) |
| Sampled enrichment ratio | ≥ 8× (target 10×) |
| `.windsurfrules` version | v5 (STATE CONTEXT added; 11 layers) |
| HITL dimensions | 7 (Day 9 adds 8th: Confidence Handling) |
| AWS Bedrock invocations | ~25 today (cumulative ~25 of 50) |
| MR commits | 3 |

---

## What's coming on Day 9

Module 9 — **Real-Time ML/DL Inference (SageMaker Serverless)**. Cascade adds the 10th Lambda (`accelya-predict-<learner>`) and extends `inference-pipeline-<learner>` with an ASL Parallel branch (Bedrock + SageMaker side-by-side). Same consumer. `.windsurfrules` v5 → **v6** adds `MODEL CONTEXT` block (12th layer): model choice, input shape, confidence threshold, fallback. **8th HITL dimension** added: **Confidence Handling**.

Bring tomorrow:
- All 9 M8 Lambdas Active
- `inference-pipeline-<learner>` ACTIVE
- ESM Enabled
- `SAMPLE_RATE=10` reset
- `.windsurfrules` v5

---

*See `Day8_Module8_Agentic_Streaming.pptx` slides 20-28 for the deck's visual treatment.*
