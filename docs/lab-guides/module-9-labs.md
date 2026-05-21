# Module 9 — Lab Guides (Standalone Reference)

> The Day 9 deck has these labs on slides 20-28; this file is your standalone reference.

---

## Day 9 prerequisites

```bash
cd accelya-agentic-aws
git checkout main && git pull --ff-only
git checkout -b module-9-<your-name>

export LEARNER=<your-name>
export AWS_REGION=ap-south-1
export BUCKET=accelya-airline-data-ap-south-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

Confirm Day 8 artefacts:

```bash
# 4 M8 Lambdas Active
for FN in accelya-producer-$LEARNER accelya-consumer-$LEARNER \
          accelya-bedrock-enrich-$LEARNER accelya-persist-enriched-$LEARNER; do
  STATE=$(aws lambda get-function --function-name $FN --region $AWS_REGION \
    --query 'Configuration.State' --output text)
  printf "  %-50s %s\n" "$FN" "$STATE"
done

# State machine
aws stepfunctions list-state-machines --region $AWS_REGION \
  --query "stateMachines[?name=='inference-pipeline-$LEARNER'].name" --output text

# Day 8 .windsurfrules v5
head -2 .windsurfrules    # v5 + STATE CONTEXT
```

Close all Cascade chats. MODEL CONTEXT pickup test is in Lab 2.

---

## Lab 1 — Deploy SageMaker Serverless endpoint (45 min, PAIRS)

**Deliverable:** Endpoint ACTIVE; smoke-test returns valid response with `risk_score+confidence+model_version`; `ModelSetupTime` cold-start metric > 0; `/reviews/m9-endpoint-smoke-test.md`; `prompts/v12_model.txt` + `.windsurfrules` v6 committed.

### Step 1 — Promote `.windsurfrules` v5 → v6

```bash
diff .windsurfrules docs/.windsurfrules-v6.template | head -60
cp docs/.windsurfrules-v6.template .windsurfrules

# Copy the 12-layer prompt
cp docs/v12_model.txt prompts/v12_model.txt 2>/dev/null || \
  cp prompts/v11_stream_state.txt prompts/v12_model.txt
# Or just use the canonical one in the repo

git add .windsurfrules prompts/v12_model.txt
git commit -m "module-9: promote .windsurfrules v5 → v6 (MODEL CONTEXT)"
```

### Step 2 — Deploy endpoint via the script

```bash
bash scripts/deploy_m9_endpoint.sh $LEARNER
```

The script creates: IAM role, Model, EndpointConfig (ServerlessConfig 1024 MB / MaxConcurrency 5), Endpoint. Polls `wait endpoint-in-service` (~3-5 min).

Verify:

```bash
aws sagemaker describe-endpoint --endpoint-name accelya-cancel-risk-$LEARNER \
  --region $AWS_REGION \
  --query '[EndpointStatus,ProductionVariants[0].ServerlessConfig]' --output table
# Expected: InService / {MemorySizeInMB:1024, MaxConcurrency:5}
```

### Step 3 — Smoke test the endpoint

```bash
PAYLOAD='{"booking_id":"BK-TEST-001","fare_amount":2845.00,"refund_lag_hours":2.5,"prior_cancels":0}'

aws sagemaker-runtime invoke-endpoint \
  --endpoint-name accelya-cancel-risk-$LEARNER \
  --content-type application/json \
  --accept application/json \
  --cli-binary-format raw-in-base64-out \
  --body "$PAYLOAD" \
  --region $AWS_REGION \
  /tmp/m9-smoke-response.json

cat /tmp/m9-smoke-response.json | python3 -m json.tool
# Expected: {"risk_score": 0.xx, "confidence": 0.xx, "model_version": "v1.2.3"}
```

First invocation is cold-start (1-6 s). Run it twice — the second is warm (50-300 ms).

### Step 4 — Capture cold-start metric

```bash
START=$(date -u -v-10M +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u --date='10 minutes ago' +%Y-%m-%dT%H:%M:%S)
END=$(date -u +%Y-%m-%dT%H:%M:%S)

aws cloudwatch get-metric-statistics \
  --namespace AWS/SageMaker \
  --metric-name ModelSetupTime \
  --dimensions Name=EndpointName,Value=accelya-cancel-risk-$LEARNER \
               Name=VariantName,Value=AllTraffic \
  --start-time $START --end-time $END --period 60 \
  --statistics Maximum --region $AWS_REGION \
  --query 'Datapoints[].[Timestamp,Maximum]' --output table
```

Expected: at least 1 datapoint with `Maximum > 0` — that's the cold-start.

### Step 5 — Document evidence + commit

```bash
mkdir -p reviews
cat > reviews/m9-endpoint-smoke-test.md <<EOF
# M9 Lab 1 — Endpoint Smoke Test Evidence

## Endpoint
- Name:    accelya-cancel-risk-$LEARNER
- Status:  InService
- Config:  ServerlessConfig{MemorySizeInMB: 1024, MaxConcurrency: 5}

## Smoke response
\`\`\`json
$(cat /tmp/m9-smoke-response.json)
\`\`\`

## Cold-start metric
(See above table — Maximum ModelSetupTime in last 10 min)
EOF

git add scripts/deploy_m9_endpoint.sh scripts/reset_module9_endpoint.sh \
        reviews/m9-endpoint-smoke-test.md
git commit -m "module-9: SageMaker Serverless endpoint + smoke test (Lab 1)"
git push -u origin module-9-$LEARNER
```

### Lab 1 common gotchas

- **`ValidationException: ServerlessConfig cannot be set with InitialInstanceCount`** — you set both. Use only one. The Serverless block goes inside `ProductionVariants[0].ServerlessConfig`. No `InstanceType` field.
- **`ResourceLimitExceeded` on create-endpoint** — another endpoint exists for this learner. Sandbox cap = 1. Run `aws sagemaker list-endpoints --query "Endpoints[?contains(EndpointName,'$LEARNER')]"`. If anything's there, delete first.
- **First `invoke-endpoint` is slow** — cold-start. Not a bug. Run twice.
- **HTTP 415** — missing `--content-type application/json` on `invoke-endpoint`. Always pass both `--content-type` and `--accept`.
- **No `ModelSetupTime` metric** — wait 1-2 min after first invocation for CloudWatch to publish.

---

## Lab 2 — Wrapper Lambda + ASL Parallel fork (45 min, PAIRS)

**Deliverable:** Wrapper Lambda Active (count = 10 of 10); `src/common/exceptions.py` extended with TWO new exceptions; ASL updated to include Parallel + Choice + Catch; end-to-end execution SUCCEEDED with both branches; `/reviews/HITL_REVIEW-m9-inference.md` ≥ 19/24.

### Step 1 — Cascade scaffolds the wrapper Lambda

Open a **fresh** Cascade chat. Prompt:

```
@cascade Read .windsurfrules v6 + prompts/v12_model.txt. Using MODEL CONTEXT,
scaffold src/predict/handler.py:

- Wrapper for SageMaker invoke_endpoint
- Env vars: ENDPOINT_NAME, CONFIDENCE_THRESHOLD (default '0.7')
- boto3 client config: connect_timeout=5, read_timeout=35, retries={'max_attempts':0}
- ContentType + Accept = 'application/json' BOTH set
- Exception mapping:
    (ReadTimeoutError, ConnectTimeoutError) → EndpointColdStartTimeout
    ServiceUnavailableException OR HTTP 503 → EndpointThrottleException
    ModelError/InternalFailure + HTTP 504 → EndpointColdStartTimeout
    ModelError (non-504) → PipelineError
- Body parsing 5-step (read, decode, validate model_version, coerce, wrap as PipelineError)
- low_confidence = confidence < THRESHOLD (NORMAL OUTPUT FLAG)
- EMF metrics with ModelId + Function dimensions

Plus extend src/common/exceptions.py with EndpointColdStartTimeout and
EndpointThrottleException (subclasses of PipelineError). DO NOT add
LowConfidencePrediction.
```

**Reference handler** (compare with Cascade's output): `src/predict/handler.py`.

### Step 2 — Verify exceptions ladder

```bash
grep -E "class (Endpoint|Low)" src/common/exceptions.py
# Expected output should include EndpointColdStartTimeout and EndpointThrottleException
# Should NOT include LowConfidencePrediction
```

### Step 3 — Update the state machine ASL

```bash
# Pre-validate before update
aws stepfunctions validate-state-machine-definition \
  --region $AWS_REGION \
  --definition file://infra/inference-pipeline.asl.json \
  --query '{result:result, diagnostics:diagnostics}' \
  --output json
# Expected: {"result": "OK", "diagnostics": []}
```

If the validate fails, STOP. Fix the ASL before updating.

### Step 4 — Deploy wrapper Lambda + update state machine

```bash
# Build wrapper Lambda zip
rm -rf /tmp/m9-build && mkdir -p /tmp/m9-build/common
cp src/predict/handler.py /tmp/m9-build/
cp src/common/__init__.py /tmp/m9-build/common/
cp src/common/exceptions.py /tmp/m9-build/common/
( cd /tmp/m9-build && zip -qr /tmp/predict.zip . )

PIPELINE_ROLE_ARN=$(aws iam get-role --role-name accelya-stream-role-$LEARNER \
  --query 'Role.Arn' --output text)
ENDPOINT_NAME=accelya-cancel-risk-$LEARNER

aws lambda create-function \
  --function-name accelya-predict-cancel-risk-$LEARNER \
  --runtime python3.12 \
  --architectures x86_64 \
  --handler handler.handler \
  --role $PIPELINE_ROLE_ARN \
  --memory-size 512 --timeout 45 \
  --zip-file fileb:///tmp/predict.zip \
  --environment "Variables={ENDPOINT_NAME=$ENDPOINT_NAME,CONFIDENCE_THRESHOLD=0.7}" \
  --region $AWS_REGION
aws lambda wait function-active-v2 --function-name accelya-predict-cancel-risk-$LEARNER \
  --region $AWS_REGION

# Extend stream role with sagemaker:InvokeEndpoint
SM_INVOKE_POLICY=$(cat <<EOF
{
  "Version":"2012-10-17",
  "Statement":[{
    "Effect":"Allow",
    "Action":["sagemaker:InvokeEndpoint"],
    "Resource":"arn:aws:sagemaker:$AWS_REGION:$ACCOUNT_ID:endpoint/$ENDPOINT_NAME"
  }]
}
EOF
)
echo "$SM_INVOKE_POLICY" > /tmp/m9-invoke.json
aws iam put-role-policy --role-name accelya-stream-role-$LEARNER \
  --policy-name "M9InvokeEndpointPolicy" \
  --policy-document file:///tmp/m9-invoke.json

# Create SQS review queue (low-confidence sink)
aws sqs create-queue --queue-name model-review-queue-$LEARNER \
  --attributes '{"VisibilityTimeout":"60","MessageRetentionPeriod":"1209600"}' \
  --region $AWS_REGION
export MODEL_REVIEW_QUEUE_URL=$(aws sqs get-queue-url \
  --queue-name model-review-queue-$LEARNER --region $AWS_REGION \
  --query QueueUrl --output text)

# Update state machine — render ASL with envsubst
export AWS_REGION AWS_ACCOUNT_ID=$ACCOUNT_ID LEARNER BUCKET_NAME=$BUCKET
envsubst < infra/inference-pipeline.asl.json > /tmp/inference-pipeline-rendered.asl.json

aws stepfunctions validate-state-machine-definition \
  --region $AWS_REGION \
  --definition file:///tmp/inference-pipeline-rendered.asl.json \
  --query 'result' --output text
# Expected: OK

SM_ARN=$(aws stepfunctions list-state-machines --region $AWS_REGION \
  --query "stateMachines[?name=='inference-pipeline-$LEARNER'].stateMachineArn" --output text)

aws stepfunctions update-state-machine \
  --state-machine-arn $SM_ARN \
  --definition file:///tmp/inference-pipeline-rendered.asl.json \
  --region $AWS_REGION
```

### Step 5 — End-to-end test

```bash
# Send 1 event via M8 producer
python3 -m scripts.gen_m9_test_batch --high-conf 1 --low-conf 0 --out /tmp/m9-1-event.json
aws lambda invoke \
  --function-name accelya-producer-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/m9-1-event.json \
  --region $AWS_REGION /tmp/out.json

# Wait 30s, then check executions
sleep 30
aws stepfunctions list-executions --state-machine-arn $SM_ARN --region $AWS_REGION \
  --max-items 5 --query 'executions[].[status,name]' --output table
# Expected: 1 SUCCEEDED execution
```

Open the execution in the AWS console (Workflow Studio) — verify both Parallel branches ran.

### Step 6 — HITL review on 8 dimensions

```bash
cat > reviews/HITL_REVIEW-m9-inference.md <<'EOF'
# HITL Review — m9 inference (Lab 1 + Lab 2 + Lab 3 deliverables)

Reviewer: <pair partner name>

| Dim | Score 0-3 | Evidence |
|---|---|---|
| Correctness         | _/3 | Bedrock + Predict in Parallel; Choice on low_confidence |
| Safety              | _/3 | ContentType + Accept set; no PII in logs |
| Idempotency         | _/3 | Wrapper stateless; ASL Parallel re-runs safe |
| Observability       | _/3 | EMF per Lambda with named dimensions |
| Cost                | _/3 | MaxConcurrency=5; ASL Catch prevents runaway retries |
| Schema Discipline   | _/3 | model_version persisted; envelope preserved |
| Per-PK Ordering     | _/3 | Inherited from D7-8; no PK changes |
| Confidence Handling | _/3 | Threshold env-driven; low-conf flag (NOT exception); SQS+S3 sinks |

**Total: _/24. Pass at ≥19/24 AND every dim ≥2/3.**

## Notes
- ...
EOF

git add src/predict/ src/common/exceptions.py infra/inference-pipeline.asl.json \
        reviews/HITL_REVIEW-m9-inference.md
git commit -m "module-9: wrapper Lambda + ASL Parallel + 8-dim HITL (Lab 2)"
git push
```

### Lab 2 common gotchas

- **Cascade adds `LowConfidencePrediction` exception** — STATE/MODEL CONTEXT forbids; low-conf is a flag. Push back.
- **Lambda timeout 30s** — wrapper needs 45s (must be > boto3 35s). 30s gets killed by Lambda runtime before boto3 raises ColdStartTimeout.
- **`update-state-machine` returns 200 OK but next execution fails** — ASL was malformed. ALWAYS validate before update.
- **ASL doesn't see `low_confidence`** — Cascade may have written `low_confidence` as a string. Verify in the rendered JSON it's `true` (boolean).
- **Wrapper hits 415 errors** — Cascade forgot `Accept='application/json'`. Both ContentType AND Accept required.
- **Predict Lambda denies bedrock-runtime IAM access** — wrong. Predict doesn't call Bedrock; just SageMaker. Don't add bedrock-runtime perms.

---

## Lab 3 — Confidence routing demo + endpoint cleanup (45 min, SOLO)

**Deliverable:** 7 high-conf events in `enriched/`; 3 low-conf in `model-review-queue` SQS + S3 audit; **endpoint DELETED**; `/reviews/m9-confidence-routing-evidence.md`; MR shows 3 commits.

### Step 1 — Generate 10-event test batch

```bash
python3 -m scripts.gen_m9_test_batch --high-conf 7 --low-conf 3 \
  --out /tmp/m9-10-events.json
```

### Step 2 — Send via producer

```bash
aws lambda invoke \
  --function-name accelya-producer-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/m9-10-events.json \
  --region $AWS_REGION /tmp/m9-producer-out.json

cat /tmp/m9-producer-out.json | python3 -m json.tool
# Expected: submitted_count=10, failed_count=0

# Wait 60s for state machine to drain
sleep 60
```

### Step 3 — Verify SQS queue depth = 3

```bash
QUEUE_URL=$(aws sqs get-queue-url --queue-name model-review-queue-$LEARNER \
  --region $AWS_REGION --query QueueUrl --output text)
aws sqs get-queue-attributes --queue-url $QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages \
  --region $AWS_REGION
# Expected: ApproximateNumberOfMessages = 3
```

### Step 4 — Verify enriched/ count = 10 (7 + 3, all persisted) and review/ = 3

```bash
echo "--- enriched/ count (all 10 should be there, low-conf has low_confidence:true) ---"
aws s3 ls s3://$BUCKET/enriched/$LEARNER/ --recursive --region $AWS_REGION | wc -l

echo "--- review/ audit sidecars (3 expected) ---"
aws s3 ls s3://$BUCKET/review/$LEARNER/model_low_confidence/ --recursive --region $AWS_REGION | wc -l
```

### Step 5 — Inspect one low-conf record

```bash
SAMPLE=$(aws s3 ls s3://$BUCKET/review/$LEARNER/model_low_confidence/ --recursive --region $AWS_REGION | head -1 | awk '{print $4}')
aws s3 cp s3://$BUCKET/$SAMPLE /tmp/m9-review-sample.json --region $AWS_REGION
cat /tmp/m9-review-sample.json | python3 -m json.tool
# Expected: contains low_confidence=true, confidence=0.xx (< 0.7)
```

### Step 6 — DELETE endpoint + cleanup + commit

```bash
bash scripts/cleanup_module9.sh $LEARNER
```

That deletes endpoint + endpoint-config + model. Verify:

```bash
aws sagemaker list-endpoints --region $AWS_REGION \
  --query "length(Endpoints[?contains(EndpointName,'$LEARNER')])" --output text
# Expected: 0
```

Document + commit:

```bash
cat > reviews/m9-confidence-routing-evidence.md <<EOF
# M9 Lab 3 — Confidence Routing Evidence

## Test setup
- 10 events sent: 7 high-conf (features tuned > 0.7), 3 low-conf (mid-range)
- SAMPLE_RATE=10 on bedrock-enrich (unchanged from Day 8)

## SQS review-queue depth
ApproximateNumberOfMessages: 3 (matches expected low-conf count)

## S3 outcomes
- enriched/$LEARNER/:                    10 files (all 10 persisted)
- review/$LEARNER/model_low_confidence/:  3 audit sidecars (matches SQS)

## Sample low-conf record
\`\`\`json
$(cat /tmp/m9-review-sample.json)
\`\`\`

## Endpoint cleanup verification
\`aws sagemaker list-endpoints\` returns 0 endpoints for $LEARNER.
EOF

git add reviews/m9-confidence-routing-evidence.md scripts/cleanup_module9.sh \
        scripts/gen_m9_test_batch.py
git commit -m "module-9: confidence routing evidence + cleanup (Lab 3)"
git push
```

### Lab 3 common gotchas

- **Low-conf events ALL still go to enriched/** — that's correct. They get persisted with `low_confidence:true` AND ALSO go to the SQS review queue + S3 audit. The Choice routes to BOTH paths; `Persist` always runs at the end.
- **SQS depth = 0** — your low-conf events came back as `low_confidence:false`. Either the model's threshold is misaligned with the test generator, or your Choice variable path is wrong (should be `$.parallel[1].low_confidence`).
- **Endpoint won't delete** — there's an in-flight invocation. Wait 60s and retry.
- **`reset_module9_endpoint.sh` says model still exists** — endpoint-config may have a reference. The script handles ordering; if it fails, run `delete-endpoint-config` manually first, then `delete-model`.
- **CRITICAL — endpoint left running** — sandbox cap = 1. Day 10/11/12 will fail. Verify `list-endpoints` returns 0 before pushing.

---

## End-of-module cleanup

```bash
bash scripts/cleanup_module9.sh $LEARNER
```

The script:
1. DELETES endpoint + endpoint-config + model (sandbox cap = 1)
2. Verifies Lambda count = 10 (final cap)
3. Verifies state machine has Parallel + Choice
4. Reports Bedrock budget

---

## Day 9 in numbers

| Metric | Value |
|---|---|
| New Lambdas | **1** (`accelya-predict-cancel-risk-<learner>`) |
| Cumulative Lambdas | **10 of 10 (FINAL CAP)** |
| SageMaker endpoints | +1 / -1 (deleted at end of Lab 3) |
| State machine | extended in place; same `inference-pipeline-<learner>` |
| SQS queues new | 1 (`model-review-queue-<learner>`) |
| `.windsurfrules` version | v6 (MODEL CONTEXT added; 12 prompt layers) |
| HITL dimensions | 8 (Confidence Handling added) |
| AWS Bedrock invocations | ~5 today (cumulative ~30-35 of 50) |
| MR commits | 3 |

---

## What's coming on Day 10

Module 10 — **Observability, Security & Cost**. Design-heavy; **0 new Lambdas**. Instrumentation only. `.windsurfrules` v6 → **v7** adds `OBSERVABILITY CONTEXT` (13th prompt layer): correlation IDs, EMF dimensions, X-Ray trace propagation across all 10 Lambdas + state machine + Bedrock + SageMaker calls.

Bring tomorrow:
- All 10 Lambdas Active
- `inference-pipeline-<learner>` with Parallel + Choice
- `model-review-queue-<learner>` SQS preserved
- `.windsurfrules` v6
- Endpoint **DELETED** — Day 10 doesn't need it

---

*See `Day9_Module9_RealTime_Inference.pptx` slides 20-28 for the deck's visual treatment.*
