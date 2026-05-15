# Module 5 — Lab Guides (Standalone Reference)

> The Day 5 deck has these labs on slides 20-29; this file is your standalone reference.

---

## Day 5 prerequisites

```bash
cd accelya-agentic-aws
git checkout main && git pull --ff-only
git checkout -b module-5-<your-name>

export LEARNER=<your-name>
export AWS_REGION=ap-south-1
export STAGING_BUCKET=accelya-airline-data-ap-south-1   # or your bucket

# Cohort roles created by 12_bootstrap_shared_aws_resources.sh
export PIPELINE_ROLE_ARN=$(aws iam get-role --role-name accelya-pipeline-lambda-role \
    --query 'Role.Arn' --output text)
export SFN_ROLE_ARN=$(aws iam get-role --role-name accelya-pipeline-sfn-role \
    --query 'Role.Arn' --output text)
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

Confirm Day 4 artefacts are present:

```bash
ls design/m4-batch-pipeline-design.example.md
ls design/m4-failure-modes.example.md
ls data/m4-failures/{01,02,03,04,05}-*.json
ls docs/.windsurfrules-v1-final.template
ls .windsurfrules                   # your v1-draft / v1-final from Day 4
```

Confirm Cascade is fresh:

```
Windsurf → File → Close ALL Cascade chats.
Open a NEW chat. This new chat will load your .windsurfrules v2 cleanly.
```

---

## Lab 1 — Promote .windsurfrules to v2 + Cascade-author 3 ASL Lambdas + ASL state machine (45 min, pairs)

**Deliverable:** `.windsurfrules` v2 + 3 handlers + tests + `src/common/exceptions.py` update + `infra/validator-pipeline.asl.json` + `scripts/provision_m5_resources.sh` + 3 deployed Lambdas + state machine ARN captured + `reviews/HITL_REVIEW-m5-asl.md`. MR opened with pair partner tagged.

### Step 1 — Promote .windsurfrules v1-final → v2

```bash
# Diff the v1-final template against your current .windsurfrules
diff .windsurfrules docs/.windsurfrules-v1-final.template

# Open both in Windsurf. Copy the TWO NEW BLOCKS from the v2 template:
#   - ASL CHUNK CONTEXT          (~50 lines)
#   - SQS PARTIAL-BATCH CONTEXT  (~50 lines)
# Both go between CONSTRAINTS and EXAMPLES.

cp docs/.windsurfrules-v2.template .windsurfrules
git add .windsurfrules
git commit -m "module-5: promote .windsurfrules v1-final → v2 (ASL CHUNK + SQS PARTIAL-BATCH)"
```

### Step 2 — Cascade scaffolds 3 handlers + tests

Open a **fresh** Cascade chat. Prompt:

```
@cascade Read .windsurfrules. Using ASL CHUNK CONTEXT, scaffold these three Lambdas:

  src/chunker/handler.py       - Reads raw/<file_key>, splits into chunks of 200 rows,
                                  writes each to staging/<learner>/<file_sha256>/chunk-NNNN.jsonl,
                                  returns {file_key, file_sha256, row_count, chunk_keys[]}.
                                  Raises MalformedRowError if file is not parseable JSON.

  src/validator_m5/handler.py  - Reads one chunk_key, iterates rows, claims row#
                                  idempotency, schema-validates, claims business#
                                  idempotency, persists to validated/. Raises
                                  ValidationError if >50% of rows in chunk are quarantined.

  src/lander/handler.py        - Aggregates validation_results from Map output,
                                  claims file# (90d TTL), computes canonical hash,
                                  claims canonical#, writes manifest.
                                  Raises ManifestMismatchError if counts don't reconcile.

Plus tests in tests/test_chunker.py, tests/test_validator_m5.py, tests/test_lander.py.
Plus extend src/common/exceptions.py with ManifestMismatchError (PipelineError subclass).
```

Inspect Cascade's output. **Common first-draft issues:**
- Cascade puts the M5 validator at `src/validator/handler.py` (overwrites Day 2 starter). Insist on `src/validator_m5/`.
- Cascade uses `event['Records']` in the chunker. Push back: ASL CHUNK CONTEXT says no.
- Cascade tries to pass `rows[]` through ASL state. Push back: 256 KiB limit.
- Cascade reaches for boto3 resource API; we use the client API for consistency with starter code.

Reference handlers if you want to compare: `src/{chunker,validator_m5,lander,dlq_replayer,m5_test_validator}/handler.py`.

### Step 3 — Cascade scaffolds the ASL state machine

```
@cascade Author infra/validator-pipeline.asl.json.

Spec from ASL CHUNK CONTEXT:
- 3 Lambda Tasks: Chunk, Validate (inside Map), Land
- 2 control states: HasRows (Choice), NoRows (Pass)
- 4 named Catch routes: QuarantineSchemaDrift, QuarantinePartial,
                        QuarantineMalformed, NotifyOps
- Every Task: Resource=arn:aws:states:::lambda:invoke,
              Payload.$="$", OutputPath="$.Payload"
- Every Task: Retry array with named ErrorEquals (Lambda.TooManyRequestsException,
              States.Timeout), MaxAttempts 3, BackoffRate 2.0
- Every Catch: ResultPath="$.error"
- Map state: ItemsPath="$.chunk_keys", MaxConcurrency=4,
             ItemSelector builds {chunk_key, file_key, file_sha256} from parent,
             ResultPath="$.validation_results"
- Function ARNs use ${AWS_REGION}, ${AWS_ACCOUNT_ID}, ${LEARNER} placeholders.
```

Validate locally:

```bash
envsubst < infra/validator-pipeline.asl.json > /tmp/validator-pipeline.rendered.asl.json
aws stepfunctions validate-state-machine-definition \
    --region $AWS_REGION \
    --definition file:///tmp/validator-pipeline.rendered.asl.json
# Expected: "result": "OK"
```

### Step 4 — Provision the idempotency table

```bash
bash scripts/provision_m5_resources.sh $LEARNER
```

Verify:

```bash
aws dynamodb describe-table --table-name idempotency_keys_$LEARNER \
    --region $AWS_REGION --query 'Table.[TableName,TableStatus]'
aws dynamodb describe-time-to-live --table-name idempotency_keys_$LEARNER \
    --region $AWS_REGION
# Expected: TimeToLiveStatus = ENABLED, AttributeName = ttl
```

### Step 5 — Deploy 3 Lambdas + the state machine

```bash
# Build a deployment package containing src/<fn>/handler.py + src/common/
build_zip() {
  local FN=$1
  rm -rf /tmp/m5-build && mkdir -p /tmp/m5-build
  cp src/$FN/handler.py /tmp/m5-build/
  cp -r src/common /tmp/m5-build/common
  cd /tmp/m5-build && zip -qr /tmp/${FN}.zip . && cd -
}

# Chunker
build_zip chunker
aws lambda create-function \
    --function-name accelya-chunker-$LEARNER \
    --runtime python3.12 --handler handler.handler \
    --memory-size 1024 --timeout 60 \
    --role $PIPELINE_ROLE_ARN \
    --zip-file fileb:///tmp/chunker.zip \
    --environment "Variables={STAGING_BUCKET=$STAGING_BUCKET,LEARNER=$LEARNER,CHUNK_SIZE=200}" \
    --region $AWS_REGION >/dev/null
aws lambda wait function-active --function-name accelya-chunker-$LEARNER --region $AWS_REGION

# Validator (M5)
build_zip validator_m5
aws lambda create-function \
    --function-name accelya-validator-$LEARNER \
    --runtime python3.12 --handler handler.handler \
    --memory-size 1024 --timeout 60 \
    --role $PIPELINE_ROLE_ARN \
    --zip-file fileb:///tmp/validator_m5.zip \
    --environment "Variables={STAGING_BUCKET=$STAGING_BUCKET,LEARNER=$LEARNER,IDEMP_TABLE=idempotency_keys_$LEARNER}" \
    --region $AWS_REGION >/dev/null
aws lambda wait function-active --function-name accelya-validator-$LEARNER --region $AWS_REGION

# Lander
build_zip lander
aws lambda create-function \
    --function-name accelya-lander-$LEARNER \
    --runtime python3.12 --handler handler.handler \
    --memory-size 1024 --timeout 60 \
    --role $PIPELINE_ROLE_ARN \
    --zip-file fileb:///tmp/lander.zip \
    --environment "Variables={STAGING_BUCKET=$STAGING_BUCKET,LEARNER=$LEARNER,IDEMP_TABLE=idempotency_keys_$LEARNER}" \
    --region $AWS_REGION >/dev/null
aws lambda wait function-active --function-name accelya-lander-$LEARNER --region $AWS_REGION

# State machine
envsubst < infra/validator-pipeline.asl.json > /tmp/validator-pipeline.rendered.asl.json
aws stepfunctions validate-state-machine-definition \
    --region $AWS_REGION \
    --definition file:///tmp/validator-pipeline.rendered.asl.json

SM_ARN=$(aws stepfunctions create-state-machine \
    --name validator-pipeline-$LEARNER \
    --definition file:///tmp/validator-pipeline.rendered.asl.json \
    --role-arn $SFN_ROLE_ARN \
    --region $AWS_REGION --query stateMachineArn --output text)
echo "State machine ARN: $SM_ARN"
```

Smoke-test against one of Day 4's broken files:

```bash
# Copy the schema-drift file to your raw/ prefix
aws s3 cp data/m4-failures/01-schema-drift.json \
    s3://$STAGING_BUCKET/raw/synthetic/m4-failures/01-schema-drift.json \
    --region $AWS_REGION

# Start an execution
aws stepfunctions start-execution \
    --state-machine-arn $SM_ARN \
    --input '{"file_key":"raw/synthetic/m4-failures/01-schema-drift.json"}' \
    --region $AWS_REGION
```

Open the Step Functions console → execution → Workflow Studio. Watch the states light up. Row 47 + 89 should land in `quarantine/schema_drift/<learner>/`; the rest should land in `validated/<learner>/`.

### Step 6 — HITL review on ASL JSON + commit

```bash
# Score on 5 dimensions; reference reviews/HITL_REVIEW_TEMPLATE.md
nano reviews/HITL_REVIEW-m5-asl.md
# Score each dim 0-3; PASS = ≥12/15 AND every dim ≥2

git add src/{chunker,validator_m5,lander}/ \
        src/common/exceptions.py \
        infra/validator-pipeline.asl.json \
        scripts/provision_m5_resources.sh \
        reviews/HITL_REVIEW-m5-asl.md \
        tests/test_*.py
git commit -m "module-5: .windsurfrules v2 + chunker/validator/lander + ASL (Lab 1)"
git push -u origin module-5-$LEARNER
```

### Lab 1 common gotchas

- **Cascade overwrites `src/validator/handler.py`** → that's Day 2's. Force `src/validator_m5/`.
- **State machine creation fails: "States.Map.ItemSelector not allowed"** → check ASL JSON; older Step Functions API uses `Parameters` inside Map iterators. New API supports `ItemSelector` + `ItemProcessor`. Use new API.
- **Validator returns string `file_sha256`, Land expects key `file_sha256`** → check Map `ItemSelector` is passing `file_sha256.$: "$.file_sha256"` through, AND Validate output preserves it in the return dict.
- **`InvalidParameterValueException: zip file too large`** → you accidentally zipped `__pycache__` or virtualenv. Use the `build_zip` helper above.
- **DynamoDB TTL not enabled** → `provision_m5_resources.sh` handles this; if you skipped the script and created the table by hand, run `aws dynamodb update-time-to-live`.
- **Schema-drift row routes to malformed instead of schema_drift** → check the Catch order in ASL; `MalformedRowError` should be matched first, `ValidationError` second.

---

## Lab 2 — Standalone partial-batch demo (45 min, SOLO)

**Deliverable:** Test queue + DLQ + Lambda + ESM provisioned; Demo A + Demo B observed; `reviews/m5-partial-batch-evidence.md` with Logs Insights output. MR shows 2 commits.

> **This is a SEPARATE teaching demo. NOT the main pipeline.** Resources here are deleted by `cleanup_module5.sh` at EOD.

### Step 1 — Provision test queues

```bash
# DLQ first (no redrive policy)
aws sqs create-queue --queue-name m5-test-dlq-$LEARNER \
    --attributes '{"VisibilityTimeout":"30","MessageRetentionPeriod":"1209600"}' \
    --region $AWS_REGION
TEST_DLQ_URL=$(aws sqs get-queue-url --queue-name m5-test-dlq-$LEARNER \
    --region $AWS_REGION --query QueueUrl --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url $TEST_DLQ_URL \
    --attribute-names QueueArn --region $AWS_REGION \
    --query 'Attributes.QueueArn' --output text)

# Main test queue with redrive
REDRIVE="{\"deadLetterTargetArn\":\"$DLQ_ARN\",\"maxReceiveCount\":\"3\"}"
aws sqs create-queue --queue-name m5-test-queue-$LEARNER \
    --attributes "{\"VisibilityTimeout\":\"65\",\"MessageRetentionPeriod\":\"1209600\",\"RedrivePolicy\":\"$REDRIVE\"}" \
    --region $AWS_REGION

# Note: VisibilityTimeout 65 = 6 * Lambda timeout (10s) + batching window (5s)

TEST_QUEUE_URL=$(aws sqs get-queue-url --queue-name m5-test-queue-$LEARNER \
    --region $AWS_REGION --query QueueUrl --output text)
QUEUE_ARN=$(aws sqs get-queue-attributes --queue-url $TEST_QUEUE_URL \
    --attribute-names QueueArn --region $AWS_REGION \
    --query 'Attributes.QueueArn' --output text)

echo "TEST_QUEUE_URL=$TEST_QUEUE_URL"
echo "TEST_DLQ_URL=$TEST_DLQ_URL"
```

### Step 2 — Deploy m5-test-validator

```bash
# Reference handler: src/m5_test_validator/handler.py
build_zip m5_test_validator    # the same helper from Lab 1

aws lambda create-function \
    --function-name m5-test-validator-$LEARNER \
    --runtime python3.12 --handler handler.handler \
    --memory-size 512 --timeout 10 \
    --role $PIPELINE_ROLE_ARN \
    --zip-file fileb:///tmp/m5_test_validator.zip \
    --environment "Variables={STAGING_BUCKET=$STAGING_BUCKET,LEARNER=$LEARNER,IDEMP_TABLE=idempotency_keys_$LEARNER,FORCE_TRANSIENT_ENABLED=true}" \
    --region $AWS_REGION >/dev/null
aws lambda wait function-active --function-name m5-test-validator-$LEARNER --region $AWS_REGION
```

### Step 3 — Wire SQS event source mapping

```bash
aws lambda create-event-source-mapping \
    --function-name m5-test-validator-$LEARNER \
    --event-source-arn $QUEUE_ARN \
    --batch-size 10 \
    --maximum-batching-window-in-seconds 5 \
    --function-response-types ReportBatchItemFailures \
    --scaling-config 'MaximumConcurrency=5' \
    --region $AWS_REGION

# Verify
aws lambda list-event-source-mappings \
    --function-name m5-test-validator-$LEARNER \
    --region $AWS_REGION \
    --query 'EventSourceMappings[].[State,FunctionResponseTypes,BatchSize]'
# Expected: [["Enabled",["ReportBatchItemFailures"],10]]
```

### Step 4 — Demo A: schema-drift quarantine (not a failure)

```bash
# Generate a 10-row batch with row 4 poisoned (missing fare_amount)
python3 -m scripts.gen_test_batch --rows 10 --poison-line 4 \
    --out /tmp/m5-test-batch-sqs.json

# Send
aws sqs send-message-batch \
    --queue-url $TEST_QUEUE_URL \
    --entries file:///tmp/m5-test-batch-sqs.json \
    --region $AWS_REGION

# Wait ~30s, then verify in Logs Insights
sleep 30

QUERY='fields @timestamp, event, reason, message_id | filter event in ["row_landed","row_quarantined"] | sort @timestamp desc | limit 20'
START=$(($(date +%s) - 120))
END=$(date +%s)

aws logs start-query \
    --log-group-name /aws/lambda/m5-test-validator-$LEARNER \
    --start-time $START --end-time $END \
    --query-string "$QUERY" \
    --region $AWS_REGION
# Wait a few seconds, then aws logs get-query-results --query-id <id>
```

Expected: 9 `row_landed`, 1 `row_quarantined reason=schema_drift`. **Test-DLQ stays empty.**

```bash
aws sqs get-queue-attributes --queue-url $TEST_DLQ_URL \
    --attribute-names ApproximateNumberOfMessages --region $AWS_REGION
# Expected: ApproximateNumberOfMessages = 0
```

### Step 5 — Demo B: forced transient (does reach DLQ)

```bash
aws sqs send-message \
    --queue-url $TEST_QUEUE_URL \
    --message-body '{"file_key":"sqs/lab2/recovery.json","line_no":1,"row":{"settlement_id":"BSP-2026-W19-RECOVER-001","bsp_cycle":"2026-W19","airline_code":"AI","pnr":"REC001","fare_class":"Y","od_pair":"BOM-LHR","ticket_number":"098-9999999999999","issue_date":"2026-05-09T11:42:00+05:30","fare_amount":2845.0,"currency":"INR","agency_iata":"14305820","source_system":"BSP"},"mode":"force_transient"}' \
    --message-attributes '{"error_type":{"DataType":"String","StringValue":"TransientError"},"replay_attempt":{"DataType":"String","StringValue":"0"}}' \
    --region $AWS_REGION

# Wait for 3 retries * 65s visibility ≈ 240s
echo "Waiting 240s for retries to exhaust and DLQ to land..."
sleep 240

aws sqs get-queue-attributes --queue-url $TEST_DLQ_URL \
    --attribute-names ApproximateNumberOfMessages --region $AWS_REGION
# Expected: ApproximateNumberOfMessages = 1
```

Peek at the DLQ message and verify `error_type` is preserved:

```bash
aws sqs receive-message --queue-url $TEST_DLQ_URL \
    --message-attribute-names All \
    --visibility-timeout 0 \
    --region $AWS_REGION \
    --query 'Messages[0].MessageAttributes.error_type'
# Expected: {"StringValue": "TransientError", "DataType": "String"}
```

### Step 6 — Document the evidence + commit

```bash
nano reviews/m5-partial-batch-evidence.md
# Capture: Demo A Logs Insights output; Demo B DLQ message attribute output;
# explicit "0 batchItemFailures in Demo A" line.

git add src/m5_test_validator/handler.py scripts/gen_test_batch.py \
        reviews/m5-partial-batch-evidence.md
git commit -m "module-5: standalone partial-batch demo (Lab 2)"
git push
```

### Lab 2 common gotchas

- **`scaling-config` rejected with "ScalingConfig must be set for FIFO"** → on Standard queues, ScalingConfig is optional but supported on newer ESM versions. If your CLI rejects it, drop the flag — Demo A/B still work.
- **Demo A: messages stuck in flight** → VisibilityTimeout too short OR ESM disabled. Check `aws lambda list-event-source-mappings`.
- **Demo A: quarantine row appears in `batchItemFailures`** → **bug in your handler**. Schema failure is row-level. Open `src/m5_test_validator/handler.py` and confirm `except SchemaError` does NOT append to `failures`.
- **Demo B: DLQ stays empty after 240s** → ESM still running with `FORCE_TRANSIENT_ENABLED=false`? Or `error_type` attribute typo? Re-check Lambda env vars + message attributes.
- **`InvalidParameterValueException: Scaling configuration cannot be set when the source is paused`** → wait for ESM state = `Enabled` before sending messages.

---

## Lab 3 — DLQ replayer with 3 classifiers (45 min, pairs)

**Deliverable:** `src/dlq_replayer/handler.py` + tests + `infra/dlq-replayer.asl.json` + SNS topic + deployed Lambda + state machine + full T0→T4 cycle in `reviews/m5-dlq-replay-cycle.md`. MR shows 3 commits.

### Step 1 — Cascade scaffolds the replayer Lambda

Reference handler: `src/dlq_replayer/handler.py`. Prompt:

```
@cascade Read .windsurfrules. Author src/dlq_replayer/handler.py per Concept 5.

Requirements:
- Event in: { "max_messages": <int up to 100> }
- Three classifiers off error_type MessageAttribute:
    transient_types = {TransientError, ThrottledError, ThrottlingException,
                       TimeoutError, DependencyTimeoutError, ServiceUnavailable}
    data_types      = {SchemaError, ManifestMismatchError, MalformedRowError,
                       ValidationError, ReferenceError, TypeMismatchError}
    everything else = config
- transient -> sqs.send_message to MAIN_QUEUE_URL with replay_attempt incremented
- transient with replay_attempt >= 3 -> escalate as config
- data -> s3.put_object to quarantine/dlq_data/<learner>/<message_id>.json
- config -> sns.publish to ESCALATION_TOPIC
- Hard cap: 100 messages per invocation
- env vars: DLQ_URL, MAIN_QUEUE_URL, ESCALATION_TOPIC, QUARANTINE_BUCKET, LEARNER
- Return shape: {transient_count, data_count, config_count, processed_count, remaining_estimate}

Plus tests in tests/test_dlq_replayer.py.
```

### Step 2 — Create SNS topic + confirm subscription

```bash
ESCALATION_TOPIC=$(aws sns create-topic \
    --name accelya-pipeline-escalations-$LEARNER \
    --region $AWS_REGION --query TopicArn --output text)
echo "ESCALATION_TOPIC=$ESCALATION_TOPIC"

aws sns subscribe \
    --topic-arn $ESCALATION_TOPIC \
    --protocol email \
    --notification-endpoint <your@email> \
    --region $AWS_REGION

# Open your email inbox.
# Click the confirmation link in the "AWS Notification - Subscription Confirmation" email.
```

### Step 3 — Deploy replayer Lambda + state machine

```bash
build_zip dlq_replayer

aws lambda create-function \
    --function-name accelya-dlq-replayer-$LEARNER \
    --runtime python3.12 --handler handler.handler \
    --memory-size 512 --timeout 60 \
    --role $PIPELINE_ROLE_ARN \
    --zip-file fileb:///tmp/dlq_replayer.zip \
    --environment "Variables={DLQ_URL=$TEST_DLQ_URL,MAIN_QUEUE_URL=$TEST_QUEUE_URL,ESCALATION_TOPIC=$ESCALATION_TOPIC,QUARANTINE_BUCKET=$STAGING_BUCKET,LEARNER=$LEARNER}" \
    --region $AWS_REGION >/dev/null
aws lambda wait function-active --function-name accelya-dlq-replayer-$LEARNER --region $AWS_REGION

# State machine
envsubst < infra/dlq-replayer.asl.json > /tmp/dlq-replayer.rendered.asl.json
aws stepfunctions validate-state-machine-definition \
    --region $AWS_REGION \
    --definition file:///tmp/dlq-replayer.rendered.asl.json

REPLAYER_SM_ARN=$(aws stepfunctions create-state-machine \
    --name dlq-replayer-$LEARNER \
    --definition file:///tmp/dlq-replayer.rendered.asl.json \
    --role-arn $SFN_ROLE_ARN \
    --region $AWS_REGION --query stateMachineArn --output text)
echo "REPLAYER_SM_ARN=$REPLAYER_SM_ARN"
```

### Step 4 — Apply the "fix" upstream

The poisoned message in the test-DLQ from Lab 2 came from `mode=force_transient`. Toggle the test-validator env var to simulate fixing the upstream defect:

```bash
aws lambda update-function-configuration \
    --function-name m5-test-validator-$LEARNER \
    --environment "Variables={STAGING_BUCKET=$STAGING_BUCKET,LEARNER=$LEARNER,IDEMP_TABLE=idempotency_keys_$LEARNER,FORCE_TRANSIENT_ENABLED=false}" \
    --region $AWS_REGION >/dev/null
aws lambda wait function-updated-v2 --function-name m5-test-validator-$LEARNER --region $AWS_REGION
```

### Step 5 — Run the replayer + verify recovery

```bash
EXEC_ARN=$(aws stepfunctions start-execution \
    --state-machine-arn $REPLAYER_SM_ARN \
    --input '{"max_messages":100}' \
    --region $AWS_REGION --query executionArn --output text)
echo "Execution: $EXEC_ARN"

# Wait for execution to finish
sleep 10
aws stepfunctions describe-execution --execution-arn $EXEC_ARN \
    --region $AWS_REGION --query '[status,output]' --output text

# Expected output: status=SUCCEEDED;
# output={transient_count:1, data_count:0, config_count:0, processed_count:1}

# Wait for replayed message to make it back through the test pipeline
sleep 20

# Verify recovery: the BSP-2026-W19-RECOVER-001 settlement should be in validated/
aws s3 ls s3://$STAGING_BUCKET/validated/$LEARNER/2026-W19/ --region $AWS_REGION | grep RECOVER
# Expected: BSP-2026-W19-RECOVER-001.json
```

### Step 6 — Document the cycle + commit

```bash
nano reviews/m5-dlq-replay-cycle.md
# Capture timeline:
#   T0 (Lab 2 step 5):   original send with mode=force_transient
#   T1 (~10s later):     test-validator returns batchItemFailures = [msg_id]
#   T2 (~240s later):    message lands in test-DLQ with error_type=TransientError
#   T3 (Lab 3 step 4):   FORCE_TRANSIENT_ENABLED=false applied
#   T4 (Lab 3 step 5):   replayer re-drives → test-validator succeeds → validated/

git add src/dlq_replayer/ infra/dlq-replayer.asl.json \
        reviews/m5-dlq-replay-cycle.md tests/test_dlq_replayer.py
git commit -m "module-5: DLQ replayer + first cycle (Lab 3)"
git push

# Update MR description on GitHub:
#   M5 Lab 1 — .windsurfrules v2 + chunker/validator/lander + ASL
#   M5 Lab 2 — standalone partial-batch demo
#   M5 Lab 3 — DLQ replayer + first replay cycle
# Tag your pair partner as reviewer.
```

### Lab 3 common gotchas

- **Replayer skips the transient message** → check classifier ordering. `transient_types` must be checked BEFORE `data_types`.
- **Replayer succeeds but DLQ still has the message** → `sqs.delete_message` not called. Look at the handler's flow — delete happens AFTER the action succeeds.
- **SNS publish hangs** → email subscription not confirmed. Check your inbox.
- **Replayed message fails again in the main queue** → `FORCE_TRANSIENT_ENABLED=false` not applied OR Lambda not updated. Check `aws lambda get-function-configuration --query 'Environment.Variables.FORCE_TRANSIENT_ENABLED'`.
- **Replayer re-drives faster than the upstream fix** → set `MAX_REPLAY_ATTEMPTS = 3` and don't loop the state machine; one execution = one drain pass.

---

## End-of-module cleanup

```bash
bash scripts/cleanup_module5.sh $LEARNER
```

Deletes the Lab 2 standalone test stack. Preserves the main pipeline + replayer. Reports remaining state.

---

## Day 5 in numbers

| Metric | Value |
|---|---|
| Programme Lambdas deployed | 4 (chunker, validator, lander, dlq_replayer) |
| Lab-only Lambdas deleted | 1 (m5-test-validator) |
| Lambda count cumulative | 5 of 10 (D2 starter + 4 today) |
| State machines | 2 (validator-pipeline + dlq-replayer) |
| DynamoDB tables | 1 (idempotency_keys_<learner>) |
| SNS topics | 1 (accelya-pipeline-escalations-<learner>) |
| Full DLQ replay cycles | 1 |
| AWS Bedrock invocations | ~0 today; cumulative ~2-5 of 50 |
| `.windsurfrules` version | v2 |
| PR commits | 3 |

---

## What's coming on Day 6

Module 6 — Data Transformation, Cataloguing & Analytics. **Today's `validated/<learner>/` becomes tomorrow's Glue Crawler input.** `.windsurfrules` promotes to v3 with the `CATALOG CONTEXT` block: partition columns (`ingest_date`, `source_system`), Parquet output, Athena workgroup. One new Lambda (ETL); count → 6 of 10.

Bring today's branch + `validated/` outputs + `idempotency_keys_<learner>` table — Day 6's Cascade prompts reference these as project context.

---

*See `Day5_Module5_Agentic_Batch_Implementation.pptx` slides 20-29 for the deck's full visual treatment.*
