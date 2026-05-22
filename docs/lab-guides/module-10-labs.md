# Module 10 — Lab Guides (Standalone Reference)

> The Day 10 deck has these labs on slides 23-32; this file is your standalone reference.

---

## 🌅 Day 10 morning — daily-reset bootstrap

> **Read this first.** The Pluralsight sandbox **resets every night**. At 09:00
> your AWS account has zero resources. Before any Day-10 lab can run, you need
> all 10 Lambdas + state machine + Kinesis + DDB + SQS + SageMaker endpoint
> back up. We've made this a one-paste operation.

### Option A — Cascade-orchestrated (recommended)

In Windsurf, open the workflow palette and run:

```
/day10-bootstrap
```

Cascade reads `.windsurf/workflows/day10-bootstrap.md`, prompts you for your
learner name, runs every step, verifies each one, and applies documented fixes
inline if anything fails. ~8-12 minutes cold; ~2 on a re-run.

### Option B — manual one-paste

If you're not in Windsurf or prefer the shell:

```bash
cd accelya-agentic-aws/starter-repo
git checkout main && git pull --ff-only
git checkout -b module-10-<your-name>

export LEARNER=<your-name>          # lowercase, alphanumeric+hyphen
export AWS_REGION=ap-south-1

# Daily-reset bootstrap (idempotent; safe to re-run)
bash scripts/bootstrap_day10.sh $LEARNER
```

The script's final STAGE F summary tells you everything that's now Active. You
need `Lambda count: 10 / 10` and Step Function status `ACTIVE` before
proceeding. If anything is MISSING, re-run; it's idempotent.

### Option B(skip) — endpoint cap shared with cohort

Sandbox cap is **1 SageMaker endpoint per account**. If another learner has
deployed one in your shared sandbox:

```bash
bash scripts/bootstrap_day10.sh $LEARNER --skip-endpoint
```

Day 10 labs work without the endpoint — the SageMaker dashboard widgets just
show "no data". You can pick up the endpoint later in the day when the cap
frees, by re-running the script without the flag.

### What the bootstrap creates (resource-by-resource)

| Stage | Resource | Why Day 10 needs it |
|---|---|---|
| 3 | IAM role `accelya-stream-role-<learner>` | Lambda execution + SFN |
| 4 | Kinesis stream `cancellation-events-<learner>` (2 shards) | Producer → consumer pipeline |
| 5 | DynamoDB `stream_seen_keys_<learner>` (PAY_PER_REQUEST) | Day-7 idempotency |
| 6 | SQS `stream-dlq-<learner>` + `model-review-queue-<learner>` | DLQ + low-confidence routing |
| 7 | 5 foundational Lambdas (validator/lander/chunker/dlq-replayer/etl) | Lambda count rises 0 → 5 |
| 8 | 4 streaming Lambdas (producer/consumer/bedrock_enrich/persist_enriched) | Lambda count rises 5 → 9 |
| 9 | State machine `inference-pipeline-<learner>` with Parallel + Choice | The pipeline backbone |
| 10 | Event Source Mapping Kinesis → consumer | Stream becomes consumable |
| 11 | SageMaker endpoint `accelya-cancel-risk-<learner>` (Serverless 1024/5) | Predict path |
| 12 | Predict wrapper Lambda | Lambda count rises 9 → 10 |
| 13 | 14-day log retention + TracingConfig Active on every Lambda | Day-10 observability prep |

### Promote `.windsurfrules` to v7 (after bootstrap)

```bash
cp docs/.windsurfrules-v7.template .windsurfrules
git add .windsurfrules prompts/v13_observability.txt
git commit -m "feat(m10): promote .windsurfrules to v7 (OBSERVABILITY CONTEXT)"

head -2 .windsurfrules           # expected: '# .windsurfrules — v7 ...'
```

v7 adds the OBSERVABILITY CONTEXT block plus a DAILY RESET CONTEXT block plus
a KNOWN-ERROR REGISTER. Cascade reads this on every prompt from now on.

### End-of-day teardown (don't skip)

```bash
bash scripts/bootstrap_day10.sh $LEARNER --teardown
```

Your sandbox resets overnight anyway — but this frees the **shared SageMaker
endpoint cap** for tonight's overnight sessions if any.

---

## ⚡ Single-paste fast path (Day-10-specific deploy)

After the bootstrap above completes, the actual Day-10 wiring is:

```bash
bash trainer-deliverables/51_create_m10_observability.sh $LEARNER
```

This script does sub-steps A, B, C of Lab 1 + dashboard + 3 alarms + cost monitor
of Lab 2 + IAM tightening + canary of Lab 3. Same code path as the trainer runs;
idempotent; ~8 min total.

If you want to learn what each step does, follow the manual steps below instead.

> **Sandbox note**: today touches no SageMaker endpoint. Day 9's endpoint should
> already be deleted (we don't re-create it). Cost Anomaly Detection lives in
> `us-east-1`; everything else stays in `ap-south-1`.

---

## Lab 1 (45 min, pairs) — Powertools + correlation IDs + X-Ray Active

**Goal.** Every Lambda powertools-decorated. Every log line carries correlation_id. Every Lambda + the state machine TracingConfig Active. One end-to-end smoke event lights up the entire X-Ray service map as one connected trace.

### Step 0 — promote `.windsurfrules` to v7

```bash
cp docs/.windsurfrules-v7.template .windsurfrules
git add .windsurfrules && git commit -m "feat(m10): promote .windsurfrules to v7 (OBSERVABILITY CONTEXT)"
```

The new `OBSERVABILITY CONTEXT` block sits between MODEL CONTEXT (v6) and CATALOG CONTEXT. Read it once before continuing — it's the contract Cascade picks up.

Also stage the 13-layer prompt:

```bash
git add prompts/v13_observability.txt
git commit -m "feat(m10): add 13-layer prompt with OBSERVABILITY CONTEXT"
```

### Sub-step A (8 min) — `src/common/observability.py`

Open a fresh Cascade chat. Ask:

> *"Scaffold `src/common/observability.py` per the OBSERVABILITY CONTEXT block in `.windsurfrules`. It must export: `get_logger`, `get_metrics`, `get_tracer`, `get_correlation_id`, `flush_metrics_early`. Pin `aws-lambda-powertools[tracer]==2.43.1`. The `get_correlation_id` helper must implement the 4-step fallback chain."*

The module already exists in the starter repo (`src/common/observability.py`) — your Cascade output should match it within ~5% diff. If Cascade hand-rolls `logging.getLogger` instead of using `aws_lambda_powertools.Logger`, **v7 didn't pick up**. Re-check `.windsurfrules` head and re-prompt.

Run the smoke test:

```bash
cd starter-repo
python3 -m src.common.observability
```

Expected:
```
observability.py loaded. NAMESPACE=Accelya/Pipeline
powertools versions:
  aws-lambda-powertools==2.43.1
get_correlation_id smoke tests:
  empty dict          → 'corr-...'
  {event_id: x}       → 'x'
  {correlation_id: y} → 'y'
  None               → 'corr-...'
```

If `aws_lambda_powertools` isn't installed locally:

```bash
pip install 'aws-lambda-powertools[tracer]==2.43.1' --break-system-packages
```

### Sub-step B (15 min) — apply to 3 representative Lambdas

The 3 reps cover the 3 entry-point archetypes:

| Lambda | Archetype |
|---|---|
| `accelya-producer-<learner>` | Direct invoke (synchronous, no upstream envelope) |
| `accelya-bedrock-enrich-<learner>` | SFN Task (envelope with correlation_id from consumer) |
| `accelya-predict-cancel-risk-<learner>` | SFN Parallel branch + cold-start risk |

For each rep:

```bash
# 1. Edit handler.py — apply the standard skeleton from prompts/v13_observability.txt
# 2. Add aws-lambda-powertools to each Lambda's requirements.txt:
echo 'aws-lambda-powertools[tracer]==2.43.1' >> src/producer/requirements.txt
echo 'aws-lambda-powertools[tracer]==2.43.1' >> src/bedrock_enrich/requirements.txt
echo 'aws-lambda-powertools[tracer]==2.43.1' >> src/predict/requirements.txt

# 3. Re-package and deploy (one example — repeat for each)
cd src/predict
pip install -r requirements.txt -t package/ --quiet
cp ../common/observability.py package/common/
cp ../common/exceptions.py package/common/
cp handler.py package/
cd package && zip -qr /tmp/predict.zip . && cd ..
aws lambda update-function-code \
  --function-name accelya-predict-cancel-risk-$LEARNER \
  --zip-file fileb:///tmp/predict.zip \
  --region $AWS_REGION
cd ../..
```

Set TracingConfig Active on each:

```bash
for FN in accelya-producer-$LEARNER \
          accelya-bedrock-enrich-$LEARNER \
          accelya-predict-cancel-risk-$LEARNER; do
  aws lambda update-function-configuration \
    --function-name $FN \
    --tracing-config Mode=Active \
    --region $AWS_REGION
done
```

Smoke (one record through):

```bash
# Send 1 record via producer
cat > /tmp/m10-smoke-event.json <<'JSON'
{"events": [{
  "event_id": "smoke-001", "event_type": "cancellation",
  "event_time": "2026-05-21T10:00:00+00:00",
  "airline_code": "AI", "booking_date": "2026-05-20",
  "pnr": "M10TEST", "source_system": "GDS",
  "correlation_id": "smoke-001",
  "payload": {"pnr": "M10TEST", "cancel_reason_code": "WX",
              "cancellation_event_id": "CXL-M10-001",
              "booking_id": "BK-M10-001", "fare_amount": 2845.0,
              "refund_lag_hours": 2.5, "prior_cancels": 0},
  "booking_id": "BK-M10-001", "fare_amount": 2845.0,
  "refund_lag_hours": 2.5, "prior_cancels": 0
}]}
JSON

aws lambda invoke \
  --function-name accelya-producer-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/m10-smoke-event.json \
  --region $AWS_REGION /tmp/producer-out.json
cat /tmp/producer-out.json
```

Wait ~30s for SFN to drain, then:

```bash
# 1. Find the trace via CloudWatch X-Ray traces
aws xray get-trace-summaries \
  --start-time $(date -u -v-5M +%s 2>/dev/null || date -u --date='5 minutes ago' +%s) \
  --end-time   $(date -u +%s) \
  --filter-expression 'annotation.correlation_id = "smoke-001"' \
  --region $AWS_REGION \
  --query 'TraceSummaries[].Id' --output text
# Expected: 1 trace ID returned

# 2. Confirm correlation_id propagated to bedrock_enrich logs
aws logs filter-log-events \
  --log-group-name /aws/lambda/accelya-bedrock-enrich-$LEARNER \
  --filter-pattern '{$.correlation_id="smoke-001"}' \
  --region $AWS_REGION \
  --query 'events[].message' --output text | head -3
# Expected: log lines with "correlation_id":"smoke-001"
```

**Sub-step B checkpoint:** trace shows producer → consumer → SFN → bedrock_enrich + predict → persist_enriched, ONE connected graph. If the SFN trace is disconnected from the Lambda traces, you forgot the `traceHeader=` arg in consumer's `start_execution` call. Fix it before continuing.

### Sub-step C (22 min) — roll out to remaining 7

Edit + redeploy each of:

- `accelya-validator-<learner>`
- `accelya-lander-<learner>`
- `accelya-chunker-<learner>`
- `accelya-dlq-replayer-<learner>`
- `accelya-etl-json-to-parquet-<learner>`
- `accelya-consumer-<learner>` (CRITICAL — add `traceHeader=` in start_execution)
- `accelya-persist-enriched-<learner>`

Smoke after each batch of 3 (re-run the smoke event above; X-Ray map should keep extending).

### Step 4 — log retention on all 10

```bash
for FN in accelya-validator-$LEARNER accelya-lander-$LEARNER \
          accelya-chunker-$LEARNER accelya-dlq-replayer-$LEARNER \
          accelya-etl-json-to-parquet-$LEARNER \
          accelya-producer-$LEARNER accelya-consumer-$LEARNER \
          accelya-bedrock-enrich-$LEARNER accelya-persist-enriched-$LEARNER \
          accelya-predict-cancel-risk-$LEARNER; do
  aws logs put-retention-policy \
    --log-group-name /aws/lambda/$FN \
    --retention-in-days 14 \
    --region $AWS_REGION
done

# Verify
for FN in accelya-validator-$LEARNER ...; do      # same list
  RET=$(aws logs describe-log-groups \
        --log-group-name-prefix /aws/lambda/$FN \
        --region $AWS_REGION \
        --query 'logGroups[0].retentionInDays' --output text)
  printf "  %-50s %s\n" "$FN" "${RET:-NEVER_EXPIRE}"
done
# Expected: 14 on all 10
```

### Step 5 — state machine tracing

```bash
SM_ARN="arn:aws:states:$AWS_REGION:$ACCOUNT_ID:stateMachine:inference-pipeline-$LEARNER"
aws stepfunctions update-state-machine \
  --state-machine-arn $SM_ARN \
  --tracing-configuration enabled=true \
  --region $AWS_REGION
```

### Lab 1 checkpoint (deck slide 26)

| Check | Command | Expected |
|---|---|---|
| All 10 Lambdas TracingConfig Active | `aws lambda get-function-configuration --function-name accelya-validator-<learner> --query 'TracingConfig.Mode'` (repeat) | `Active` × 10 |
| State machine tracing enabled | `aws stepfunctions describe-state-machine --state-machine-arn $SM_ARN --query 'tracingConfiguration.enabled'` | `true` |
| traceHeader propagation | `grep -n 'traceHeader' src/consumer/handler.py` | At least 1 hit |
| Correlation_id in all 10 logs for smoke event | filter-log-events for smoke-001 in each log group | At least 1 hit each |
| Log retention 14 days | `describe-log-groups` query | `14` × 10 |
| `/reviews/m10-observability-trace.md` exists with trace ID | `git status` | committed |

If any FAIL: re-run the sub-step that wired that piece. Don't proceed to Lab 2 with a broken Lab 1.

---

## Lab 2 (45 min, pairs) — Dashboard + 3 alarms + 1 cost monitor + SNS

**Goal.** One dashboard that answers Flowing/Correct/Fast/Cheap. Three alarms wired to an SNS topic. One Cost Anomaly Detection monitor.

### Step 1 — SNS topic

```bash
SNS_ARN=$(aws sns create-topic \
  --name accelya-alarms-$LEARNER \
  --region $AWS_REGION \
  --query 'TopicArn' --output text)
echo "SNS: $SNS_ARN"

# Tag
aws sns tag-resource --resource-arn $SNS_ARN \
  --tags Key=programme,Value=accelya Key=owner,Value=$LEARNER Key=environment,Value=lab \
  --region $AWS_REGION

# Subscription (web placeholder; in production, email)
aws sns subscribe --topic-arn $SNS_ARN \
  --protocol email \
  --notification-endpoint $LEARNER@example.local \
  --region $AWS_REGION
# Console will show PENDING CONFIRMATION; for the lab, that's fine
```

### Step 2 — dashboard

```bash
# Render template (replace <learner> + <account>)
sed -e "s/<learner>/$LEARNER/g" \
    -e "s/<account>/$ACCOUNT_ID/g" \
    infra/dashboard-pipeline.json > /tmp/dashboard.json

# Apply
aws cloudwatch put-dashboard \
  --dashboard-name accelya-pipeline-$LEARNER \
  --dashboard-body file:///tmp/dashboard.json \
  --region $AWS_REGION

# Open it in browser:
echo "https://$AWS_REGION.console.aws.amazon.com/cloudwatch/home?region=$AWS_REGION#dashboards:name=accelya-pipeline-$LEARNER"
```

Expected: 4-row grid renders; most widgets show INSUFFICIENT_DATA until you send some traffic.

### Step 3 — 3 CW alarms

```bash
# Render alarms with SNS ARN substituted
SNS_ESC=$(echo "$SNS_ARN" | sed 's/[\/&]/\\&/g')
sed -e "s/<learner>/$LEARNER/g" \
    -e "s/<account>/$ACCOUNT_ID/g" \
    -e "s|<SNS_TOPIC_ARN>|$SNS_ARN|g" \
    infra/alarms-pipeline.json > /tmp/alarms.json

# CloudWatch put-metric-alarm doesn't accept bulk JSON — apply each individually
python3 <<PY
import json, subprocess
with open('/tmp/alarms.json') as f: spec = json.load(f)
for alarm in spec['alarms']:
    # Drop the AWS-internal _comment fields we added
    a = {k: v for k, v in alarm.items() if not k.startswith('_')}
    args = ['aws','cloudwatch','put-metric-alarm','--region','$AWS_REGION']
    for k, v in a.items():
        flag = '--' + ''.join(['-' + c.lower() if c.isupper() else c for c in k]).lstrip('-')
        if isinstance(v, (list, dict)):
            args += [flag, json.dumps(v)]
        else:
            args += [flag, str(v)]
    print('→', a['AlarmName'])
    subprocess.run(args, check=True)
PY
```

(In practice the trainer deploy script `51_create_m10_observability.sh` already does this with cleaner per-alarm commands; the Python above is for learners doing it by hand.)

Verify:

```bash
aws cloudwatch describe-alarms --region $AWS_REGION \
  --alarm-names iterator-age-$LEARNER bedrock-throttle-$LEARNER confidence-drift-$LEARNER \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}' --output table
# Expected: 3 alarms, state mostly INSUFFICIENT_DATA (no traffic yet)
```

### Step 4 — Cost Anomaly Detection monitor

```bash
# Monitor (us-east-1)
MONITOR_ARN=$(aws ce create-anomaly-monitor \
  --region us-east-1 \
  --anomaly-monitor "{
    \"MonitorName\": \"accelya-cost-monitor-$LEARNER\",
    \"MonitorType\": \"DIMENSIONAL\",
    \"MonitorDimension\": \"SERVICE\"
  }" \
  --query 'MonitorArn' --output text)
echo "Monitor: $MONITOR_ARN"

# Subscription (us-east-1, but SNS in ap-south-1 — cross-region OK)
aws ce create-anomaly-subscription \
  --region us-east-1 \
  --anomaly-subscription "{
    \"SubscriptionName\": \"accelya-cost-alerts-$LEARNER\",
    \"Threshold\": 10.0,
    \"Frequency\": \"DAILY\",
    \"MonitorArnList\": [\"$MONITOR_ARN\"],
    \"Subscribers\": [{\"Type\": \"SNS\", \"Address\": \"$SNS_ARN\", \"Status\": \"CONFIRMED\"}]
  }"
```

### Step 5 — smoke (TWO checks)

**Check A — SNS wiring via set-alarm-state:**

```bash
aws cloudwatch set-alarm-state \
  --alarm-name iterator-age-$LEARNER \
  --state-value ALARM \
  --state-reason "Lab 2 smoke test - manual trigger" \
  --region $AWS_REGION

# Wait 30s; check SNS subscription endpoint for the alarm message
# (or aws sns list-subscriptions-by-topic to verify there's a target)

# Reset to OK
aws cloudwatch set-alarm-state \
  --alarm-name iterator-age-$LEARNER \
  --state-value OK \
  --state-reason "Lab 2 smoke test - reset" \
  --region $AWS_REGION
```

Expected: SNS subscription (email or console) receives the ALARM and OK notifications. SNS wiring is verified end-to-end.

**Check B — metric-dimension wiring via low threshold:**

```bash
# Temporarily lower the bedrock-throttle threshold
aws cloudwatch put-metric-alarm \
  --alarm-name bedrock-throttle-$LEARNER \
  --metric-name InvocationThrottles \
  --namespace AWS/Bedrock \
  --dimensions Name=ModelId,Value=apac.anthropic.claude-3-5-sonnet-20241022-v2:0 \
  --statistic Sum --period 60 --evaluation-periods 1 --datapoints-to-alarm 1 \
  --threshold 0 --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions $SNS_ARN \
  --region $AWS_REGION

# Send 5 records via producer (some may genuinely throttle on Bedrock side)
for i in 1 2 3 4 5; do
  python3 scripts/gen_m9_test_batch.py --high-conf 1 --low-conf 0 \
    --out /tmp/m10-batch-$i.json
  aws lambda invoke \
    --function-name accelya-producer-$LEARNER \
    --cli-binary-format raw-in-base64-out \
    --payload file:///tmp/m10-batch-$i.json \
    --region $AWS_REGION /tmp/out-$i.json &
done
wait

# Check alarm state in 2-3 min
sleep 120
aws cloudwatch describe-alarms --alarm-names bedrock-throttle-$LEARNER \
  --region $AWS_REGION --query 'MetricAlarms[].StateValue' --output text
# Expected: may stay OK if no throttles fired (sandbox often doesn't throttle 5 records);
# the test is wiring, not actual throttle behaviour

# Reset threshold to production value
aws cloudwatch put-metric-alarm \
  --alarm-name bedrock-throttle-$LEARNER \
  --metric-name InvocationThrottles \
  --namespace AWS/Bedrock \
  --dimensions Name=ModelId,Value=apac.anthropic.claude-3-5-sonnet-20241022-v2:0 \
  --statistic Sum --period 300 --evaluation-periods 1 --datapoints-to-alarm 1 \
  --threshold 5 --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions $SNS_ARN \
  --region $AWS_REGION
```

> **Why we don't force a real throttle:** sandbox blocks the genuine `ThrottlingException` code path. Hammering 1000 records in 1s gets you `AccessDeniedException` or `ValidationException`, NOT `InvocationThrottles`. The two-check test (state-set + dimension-wire) verifies the alarm pipeline truthfully.

### Lab 2 checkpoint (deck slide 29)

| Check | Command | Expected |
|---|---|---|
| Dashboard live | open URL | renders, 4 rows |
| 3 alarms exist | `aws cloudwatch describe-alarms` | 3 results |
| Cost monitor exists | `aws ce get-anomaly-monitors --region us-east-1` | 1 result |
| SNS subscription active | `aws sns list-subscriptions-by-topic --topic-arn $SNS_ARN` | ≥ 1 |
| Smoke A: state-set message landed | manual check | ✓ |
| Smoke B: threshold-lowering test ran | `describe-alarms` output | ✓ |
| `/reviews/m10-dashboard-alarms.md` exists | `git status` | committed |

---

## Lab 3 (45 min, solo) — IAM tightening + Access Analyzer + safe rollout MR

**Goal.** Replace wildcards in `accelya-pipeline-policy-<learner>` with resource-scoped statements. Run Access Analyzer. Split findings. Safe-rollout (capture-prune-create-wait-canary-rollback). Open MR.

### Step 1 — pre-snapshot

```bash
ROLE=accelya-pipeline-role-$LEARNER
POLICY_NAME=accelya-pipeline-policy
POLICY_ARN=arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_NAME

# Save current (default) version
DEFAULT_VERSION=$(aws iam list-policy-versions --policy-arn $POLICY_ARN \
  --query 'Versions[?IsDefaultVersion==`true`].VersionId' --output text)
echo "PREV_VERSION=$DEFAULT_VERSION"
aws iam get-policy-version --policy-arn $POLICY_ARN --version-id $DEFAULT_VERSION \
  --query 'PolicyVersion.Document' > reviews/m10-iam-pre.json

# Count wildcards
jq '.Statement[] | select(.Resource == "*" or (.Action[]? == "*"))' reviews/m10-iam-pre.json
```

### Step 2 — draft tightened version

```bash
sed -e "s/<learner>/$LEARNER/g" \
    -e "s/<account>/$ACCOUNT_ID/g" \
    infra/iam-pipeline-policy-tightened.json > /tmp/tightened.json
```

### Step 3 — Access Analyzer

```bash
aws accessanalyzer validate-policy \
  --policy-type IDENTITY_POLICY \
  --policy-document file:///tmp/tightened.json \
  --region $AWS_REGION > /tmp/aa.json

# Classify by severity
echo ""; echo "=== ERROR + SECURITY_WARNING (BLOCK) ==="
jq -r '.findings[] | select(.findingType=="ERROR" or .findingType=="SECURITY_WARNING") | "\(.findingType): \(.findingDetails)"' /tmp/aa.json

echo ""; echo "=== GENERAL_WARNING + SUGGESTION (COMMIT for review) ==="
jq -r '.findings[] | select(.findingType=="GENERAL_WARNING" or .findingType=="SUGGESTION") | "\(.findingType): \(.findingDetails)"' /tmp/aa.json > /tmp/aa-review-comments.md
cat /tmp/aa-review-comments.md

# Gate logic
BLOCK=$(jq '[.findings[] | select(.findingType=="ERROR" or .findingType=="SECURITY_WARNING")] | length' /tmp/aa.json)
if [ "$BLOCK" -gt 0 ]; then
  echo "BLOCKED: $BLOCK ERROR/SECURITY_WARNING findings. MR cannot merge."
  exit 1
fi
echo "OK: zero ERROR/SECURITY_WARNING. Proceeding to safe rollout."
```

### Step 4 — safe rollout (capture → prune → create → wait → canary → rollback)

```bash
# Already captured PREV_VERSION above

# Prune if at 5-version cap
COUNT=$(aws iam list-policy-versions --policy-arn $POLICY_ARN \
  --query 'length(Versions)' --output text)
if [ "$COUNT" -ge 5 ]; then
  OLDEST=$(aws iam list-policy-versions --policy-arn $POLICY_ARN \
    --query 'Versions[?IsDefaultVersion!=`true`] | sort_by(@, &CreateDate) | [0].VersionId' \
    --output text)
  echo "Pruning oldest non-default: $OLDEST"
  aws iam delete-policy-version --policy-arn $POLICY_ARN --version-id $OLDEST
fi

# Create new version + set default
NEW_VERSION=$(aws iam create-policy-version \
  --policy-arn $POLICY_ARN \
  --policy-document file:///tmp/tightened.json \
  --set-as-default \
  --query 'PolicyVersion.VersionId' --output text)
echo "NEW_VERSION=$NEW_VERSION"

# IAM eventual consistency wait
echo "Sleeping 15s for IAM eventual consistency..."
sleep 15

# Canary: 1 record through the pipeline
cat > /tmp/canary-event.json <<'JSON'
{"events": [{
  "event_id": "canary-001", "event_type": "cancellation",
  "event_time": "2026-05-21T10:00:00+00:00",
  "airline_code": "AI", "booking_date": "2026-05-20",
  "pnr": "CANARY", "source_system": "GDS",
  "correlation_id": "canary-001",
  "payload": {"pnr": "CANARY", "cancel_reason_code": "WX",
              "cancellation_event_id": "CXL-CANARY", "booking_id": "BK-CANARY",
              "fare_amount": 2500.0, "refund_lag_hours": 12.0, "prior_cancels": 1},
  "booking_id": "BK-CANARY", "fare_amount": 2500.0,
  "refund_lag_hours": 12.0, "prior_cancels": 1
}]}
JSON

aws lambda invoke \
  --function-name accelya-producer-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/canary-event.json \
  --region $AWS_REGION /tmp/canary-out.json
cat /tmp/canary-out.json

# Wait 60s for SFN to settle; check status
sleep 60
SM_ARN="arn:aws:states:$AWS_REGION:$ACCOUNT_ID:stateMachine:inference-pipeline-$LEARNER"
LATEST_EXEC=$(aws stepfunctions list-executions \
  --state-machine-arn $SM_ARN --max-items 1 \
  --query 'executions[0]' --output json --region $AWS_REGION)
STATUS=$(echo "$LATEST_EXEC" | jq -r '.status')
EXEC_ARN=$(echo "$LATEST_EXEC" | jq -r '.executionArn')

echo "Canary execution: $EXEC_ARN"
echo "Canary status: $STATUS"

if [ "$STATUS" != "SUCCEEDED" ]; then
  echo "AUTO-ROLLBACK — canary did not succeed."
  aws iam set-default-policy-version \
    --policy-arn $POLICY_ARN --version-id $DEFAULT_VERSION
  echo "Rolled back to $DEFAULT_VERSION"
  exit 1
fi

echo "OK: canary SUCCEEDED. Policy version $NEW_VERSION is now the default."
```

### Step 5 — MR

```bash
git add infra/iam-pipeline-policy-tightened.json \
        reviews/m10-iam-pre.json \
        reviews/m10-iam-tightening.md
git commit -m "feat(m10): IAM tightening — wildcards → resource ARNs"

# Capture Access Analyzer comments in the MR body
cat > .gitlab-mr-body.md <<EOF
## IAM Tightening MR

**Before**: $(jq '.Statement | length' reviews/m10-iam-pre.json) statements with $(jq '[.Statement[] | select(.Resource=="*")] | length' reviews/m10-iam-pre.json) wildcard-Resource statements.

**After**: $(jq '.Statement | length' infra/iam-pipeline-policy-tightened.json) statements, 0 wildcard-Resource on write/modify verbs.

### Access Analyzer (committed for review)
$(cat /tmp/aa-review-comments.md)

### Safe rollout
- PREV_VERSION captured: $DEFAULT_VERSION
- NEW_VERSION created: $NEW_VERSION
- Canary execution: $EXEC_ARN
- Canary status: $STATUS
EOF

# Push the branch + open MR via your GitLab tooling
git push -u origin module-10-$LEARNER
# `glab mr create --description-from .gitlab-mr-body.md ...` (Day 11 introduces glab)
```

### Lab 3 checkpoint (deck slide 32)

| Check | Command | Expected |
|---|---|---|
| Pre-snapshot saved | `ls reviews/m10-iam-pre.json` | exists |
| Zero ERROR/SECURITY_WARNING from AA | grep `/tmp/aa.json` | none |
| PREV_VERSION captured | `echo $DEFAULT_VERSION` | non-empty |
| NEW_VERSION default | `aws iam get-policy --policy-arn $POLICY_ARN --query 'Policy.DefaultVersionId'` | matches `$NEW_VERSION` |
| Canary execution SUCCEEDED | `describe-execution $EXEC_ARN` | SUCCEEDED |
| MR opened with AA findings | GitLab UI | committed |
| `/reviews/m10-iam-tightening.md` exists | `git status` | committed |

---

## End-of-day cleanup (optional)

The Day-10 artefacts CARRY FORWARD into Day 11 — do NOT delete the dashboard, alarms, SNS topic, IAM policy version, or cost monitor. The only thing cleaned up at EOD is the X-Ray sampling rule override (if you created one):

```bash
bash scripts/cleanup_module10.sh $LEARNER
```

The script:
1. Removes any `accelya-lab-trace-all-<learner>` sampling rule override
2. Verifies all 10 Lambdas still Active
3. Verifies log retention 14 days on all 10 log groups
4. Reports cumulative Bedrock budget

---

## Common gotchas

### Bootstrap-time (errors learners hit while bringing up Days 1-9 resources)

| Symptom | Cause | Fix |
|---|---|---|
| `Lambda accelya-dlq-replayer-<learner> → MISSING` in pre-flight | Day-5 starter-repo handler was never deployed before today | `bash scripts/bootstrap_day10.sh $LEARNER` STAGE 7 deploys it. If the script is older, run `bash trainer-deliverables/52_deploy_dlq_replayer.sh $LEARNER` |
| `ResourceLimitExceeded` on SageMaker endpoint create | 1-endpoint-per-account sandbox cap; another learner has it | Re-run bootstrap with `--skip-endpoint`. Day-10 labs work without it; SageMaker dashboard widgets just show "no data" |
| `ExpiredToken` / `Unable to locate credentials` | Sandbox session expired | Open fresh sandbox tab; re-export AWS_* envs; re-run bootstrap |
| `Throttling: Rate exceeded` from IAM during bootstrap | Concurrent `create-role` / `attach-role-policy` calls hitting IAM throttle | Re-run; the script is idempotent and waits 8s between IAM ops |
| Bootstrap exits with `Lambda count: N / 10` (N<10) | One `src/<name>/handler.py` missing from your local repo | `git pull --ff-only` to get latest, then re-run bootstrap |

### Day-10-specific (errors during Lab 1/2/3)

| Symptom | Cause | Fix |
|---|---|---|
| X-Ray service map shows two disconnected graphs | `traceHeader=` missing on `sfn.start_execution` in consumer | Edit `src/consumer/handler.py`, redeploy |
| Dashboard widgets all INSUFFICIENT_DATA | No traffic since Lab 1 smoke | Send 5-10 records via producer; widgets populate in ~2 min |
| SNS subscription stuck in PendingConfirmation | Email subscription needs click; web is OK for the lab | Either confirm the email or set a console subscriber |
| Alarm stays INSUFFICIENT_DATA even after traffic | Metric dimension typo | `aws cloudwatch list-metrics --metric-name InvocationThrottles --namespace AWS/Bedrock` and verify ModelId matches |
| Access Analyzer flags `xray:*` as SECURITY_WARNING | False positive — `xray:PutTraceSegments` doesn't accept resource-level perms | Justify in MR comment; commit anyway (this is the `_xray_wildcard_justification` field in the policy JSON) |
| Canary execution stays RUNNING for > 60s | Tightened policy removed a permission the consumer needs (e.g. forgot `stepfunctions:StartExecution`) | Auto-rollback fires; check the SFN execution's error |
| `create-policy-version` returns `LimitExceeded: NumberOfPolicyVersions` | 5-version cap hit | Prune oldest non-default first (script handles this) |
| Cost Anomaly Detection threshold never triggers | Lab spend < $10 (correct behaviour — sandbox burn is < $1/day) | Don't try to force; the monitor is a wiring proof, not an active alert |

### Sandbox-API quirks (already fixed in the current scripts; reference only)

These were errors we hit during the trainer's first deploy. They're now
handled in `51_create_m10_observability.sh` and the JSON templates — but if
you see them, your scripts may be out of date. Run `git pull --ff-only` and
re-run the failing step.

| Error fragment | Cause | What the current scripts do |
|---|---|---|
| `Should NOT have more than 4 items` | Malformed dashboard metric tuple (nested `metric:[]`) | `infra/dashboard-pipeline.json` uses flat tuples and math objects with ≤4 keys |
| `Unknown parameter ... "Offset"` | `Offset` on metric stat is console-only, not in API | Confidence-drift alarm uses `ANOMALY_DETECTION_BAND(m_curr, 2)` with `ThresholdMetricId` |
| `Limit exceeded on dimensional spend monitor creation` | 1 DIMENSIONAL monitor per account | Script first looks for ANY existing DIMENSIONAL monitor; reuses `Default-Services-Monitor` |
| `Daily or weekly frequencies only support Email subscriptions` | SNS subscribers require `IMMEDIATE` frequency | Cost Anomaly subscription is created with `Frequency: IMMEDIATE` |
| SNS topic policy denies `costalerts.amazonaws.com` | Default SNS policy is account-internal only | Script patches the SNS topic Policy attribute to allow `costalerts.amazonaws.com:sns:Publish` |

---

*Cross-reference: deck `Day10_Module10_Observability.pptx` (38 slides). Trainer guide `trainer-deliverables/50_day10_trainer_study_guide.md`. Requirements `trainer-deliverables/48_day10_requirements_and_prep.md`.*
