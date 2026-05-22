---
description: Daily-reset bootstrap for Day 10 labs. Cascade walks the learner through bringing up all prior-day resources + Day-10 observability stack in their fresh sandbox.
---

# Day 10 Bootstrap (Cascade-orchestrated)

This workflow is for **learners** running the Day 10 labs in a Pluralsight sandbox
that **resets nightly**. Every morning, every learner must recreate all 10
Lambdas + state machine + Kinesis + DDB + SQS + IAM + SageMaker endpoint
before Day 10 instrumentation will work.

Cascade follows this workflow end-to-end. At each step Cascade:
1. Runs the command
2. Checks the verify line
3. If FAIL, applies the documented fix and retries
4. Reports the outcome before moving to the next step

## What you need before starting

- A fresh Pluralsight AWS sandbox in `ap-south-1`
- Your AWS credentials exported in this terminal (run `aws sts get-caller-identity` first)
- Repo cloned and you're on a fresh branch:
  ```bash
  git checkout main && git pull --ff-only
  git checkout -b module-10-$(whoami | tr -d ' \n')
  ```
- Your **learner name** (lowercase, alphanumeric+hyphen, starts with a letter)

## Step 1 — Set your learner suffix

Ask the user for their learner name. Validate it matches `^[a-z][a-z0-9-]*$`.
If invalid, ask again. Once valid, export it:

```bash
export LEARNER=<learner-from-user>
export AWS_REGION=ap-south-1
echo "LEARNER=$LEARNER ; AWS_REGION=$AWS_REGION"
```

**Verify:** `echo $LEARNER` returns the lowercase suffix the user provided.

## Step 2 — Sanity check the sandbox

```bash
aws sts get-caller-identity --region $AWS_REGION
```

**Verify:** returns an Account, UserId, and Arn. If `Unable to locate credentials` or
`ExpiredToken`, **STOP** and tell the user: "Your sandbox credentials are missing
or expired. Open a fresh sandbox tab, copy the AWS export commands, paste into
this terminal, then re-run /day10-bootstrap from Step 2."

## Step 3 — Verify-only pass (what's already there?)

```bash
cd /path/to/accelya-agentic-aws/starter-repo
bash scripts/bootstrap_day10.sh $LEARNER --verify-only
```

**Verify:** the script prints a STAGE F summary. Read which resources are
`MISSING` vs `Active`. If everything is `Active` and Lambda count is `10 / 10`,
**skip to Step 6**. Otherwise continue.

## Step 4 — Full bootstrap

```bash
bash scripts/bootstrap_day10.sh $LEARNER
```

This script takes 8-12 minutes cold; 2-3 minutes on re-run after partial failure.
It is idempotent — safe to re-run if anything fails partway.

**Verify (must all pass):**
- Final STAGE F summary shows `Lambda count: 10 / 10`
- Step Function status `ACTIVE`
- Kinesis stream status `ACTIVE`
- DDB table status `ACTIVE`
- SQS DLQ `OK`
- SageMaker endpoint `InService` *OR* the script was invoked with `--skip-endpoint`

**If the script exits 2** (Lambda count < 10): one of the per-day source files is
missing. Read the warning above the summary — it names which Lambda. Re-run the
script; if it still fails for the same Lambda, the starter-repo `src/<name>/handler.py`
is missing. Tell the user: "src/<name>/handler.py is missing — pull latest from
main, then re-run."

**If SageMaker endpoint creation fails with `ResourceLimitExceeded`:** sandbox cap
is 1 endpoint per account, and someone else has it. Options:
1. If working solo: ask the sandbox owner / training coordinator to clear it.
2. If in a cohort: coordinate rotation. Run with `--skip-endpoint` for now; you
   can still do Lab 1 and Lab 2; only the SageMaker dashboard widgets stay empty.
   Re-run `bash scripts/bootstrap_day10.sh $LEARNER` (without flag) when the
   cap frees up.

**If you see `Endpoint deploy failed`:** check the inner error printed. Common
ones documented in `module-10-labs.md` § Common gotchas.

## Step 5 — Promote .windsurfrules to v7

```bash
cp docs/.windsurfrules-v7.template .windsurfrules
git add .windsurfrules prompts/v13_observability.txt
git commit -m "feat(m10): promote .windsurfrules to v7 (OBSERVABILITY CONTEXT)"
```

**Verify:**
```bash
head -2 .windsurfrules
# Expected: '# .windsurfrules — v7 (Day 10 Lab 1 target state)'
```

**Why this matters:** v7 adds the OBSERVABILITY CONTEXT block. Cascade reads
this on every prompt from now on. Without v7, when Cascade scaffolds Day-10
code it will fall back to v6 defaults and skip correlation_id propagation,
EMF metrics, and the flush-early pattern.

## Step 6 — Day-10 deploy

```bash
bash trainer-deliverables/51_create_m10_observability.sh $LEARNER
```

This is the same script the trainer ran. It deploys:
- SNS topic `accelya-alarms-<learner>`
- TracingConfig=Active on all 10 Lambdas
- Log retention 14 days
- State machine tracing enabled
- CloudWatch dashboard `accelya-pipeline-<learner>` (4-row grid)
- 3 CW alarms (iterator-age, bedrock-throttle, confidence-drift via ANOMALY_DETECTION_BAND)
- AWS Cost Anomaly Detection (us-east-1, reuses Default-Services-Monitor)
- IAM Access Analyzer dry-run on the tightened policy
- 2 smoke tests (set-alarm-state + describe-alarms snapshot)

**Verify (must all pass):**
- Step `[5/8] CloudWatch dashboard accelya-pipeline-<learner>` prints `✓ Dashboard URL`
- Step `[6/8] CloudWatch alarms (3) → SNS` prints 3 `✓` lines
- Step `[7/8] AWS Cost Anomaly Detection` prints `✓ Subscription created`
- Step `[8/8] IAM tightening DRY-RUN` prints `✓ Zero ERROR/SECURITY_WARNING`
- The final `✅ Day 10 observability stack deployed` line is present

**Known-good error handling already in the script:**
- Dashboard "Should NOT have more than 4 items" — was a malformed metric tuple;
  the current `infra/dashboard-pipeline.json` has correct 4-element tuples.
- `Unknown parameter "Offset"` — was an unsupported metric stat field; the
  current alarm 3 uses `ANOMALY_DETECTION_BAND(m_curr, 2)` instead.
- `Limit exceeded on dimensional spend monitor` — script reuses the existing
  `Default-Services-Monitor` (DIMENSIONAL cap is 1 per account).
- `Daily or weekly frequencies only support Email subscriptions` — script uses
  `Frequency: IMMEDIATE` for SNS subscribers.

**If any of those errors still occur:** the JSONs or the script are out of
date. Tell the user: "Pull latest from main and re-run from Step 6."

## Step 7 — Open the dashboard

Print the dashboard URL from Step 6's output and tell the user:

> Open this URL in a fresh browser tab. Widgets will show INSUFFICIENT_DATA
> until you send some traffic — that's expected. The smoke tests in the next
> step generate traffic to light them up.

## Step 8 — End-to-end smoke

Send 1 record through the pipeline so X-Ray collects a connected trace:

```bash
cat > /tmp/m10-smoke-event.json <<EOF
{"events": [{
  "event_id": "smoke-$LEARNER-001", "event_type": "cancellation",
  "event_time": "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)",
  "airline_code": "AI", "booking_date": "$(date -u +%Y-%m-%d)",
  "pnr": "M10TEST", "source_system": "GDS",
  "correlation_id": "smoke-$LEARNER-001",
  "payload": {"pnr": "M10TEST", "cancel_reason_code": "WX",
              "cancellation_event_id": "CXL-M10-001",
              "booking_id": "BK-M10-001", "fare_amount": 2845.0,
              "refund_lag_hours": 2.5, "prior_cancels": 0},
  "booking_id": "BK-M10-001", "fare_amount": 2845.0,
  "refund_lag_hours": 2.5, "prior_cancels": 0
}]}
EOF

aws lambda invoke \
  --function-name accelya-producer-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/m10-smoke-event.json \
  --region $AWS_REGION /tmp/producer-out.json

cat /tmp/producer-out.json
```

**Verify:** `producer-out.json` contains `"submitted": 1` and `"failed": 0`.

Wait 60s for SFN to drain, then check the trace:

```bash
sleep 60
aws xray get-trace-summaries \
  --start-time $(date -u -v-5M +%s 2>/dev/null || date -u --date='5 minutes ago' +%s) \
  --end-time   $(date -u +%s) \
  --filter-expression "annotation.correlation_id = \"smoke-$LEARNER-001\"" \
  --region $AWS_REGION \
  --query 'TraceSummaries[].Id' --output text
```

**Verify:** 1 trace ID is returned.

If 0 traces returned: the X-Ray annotation isn't being set yet (it's added in
Lab 1 sub-step B when learners apply the powertools tracer decorator). That's
expected pre-Lab-1; the producer's TracingConfig is Active so the bare trace
exists — you just can't filter by annotation yet. Tell the user: "No annotated
trace yet — that's normal before Lab 1. Continue to Lab 1."

## Step 9 — You are ready for Lab 1

Tell the user:

> ✅ Day-10 environment is up.
>
> Open `starter-repo/docs/lab-guides/module-10-labs.md` and start at "Lab 1".
> The labs walk you through:
> - Lab 1 (45 min): apply `aws-lambda-powertools` + correlation IDs to all 10 Lambdas
> - Lab 2 (45 min): wire CloudWatch dashboard widgets to your traffic, set up alarms
> - Lab 3 (45 min): IAM tightening via Access Analyzer, safe rollout, MR
>
> When done at end of day:
> ```bash
> bash scripts/bootstrap_day10.sh $LEARNER --teardown
> ```
> This deletes everything you created (frees the SageMaker endpoint cap for tomorrow).
> Don't skip teardown — your sandbox resets overnight anyway, but leaving the
> endpoint up may block another learner's afternoon session.

## Troubleshooting cheat sheet

If at any point a command fails, Cascade should match the error to this table
before retrying:

| Error fragment | Cause | Fix |
|---|---|---|
| `ExpiredToken`, `Unable to locate credentials` | Sandbox creds expired / not exported | Open fresh sandbox tab; re-export AWS_* envs; restart workflow |
| `ResourceLimitExceeded ... endpoint` | 1-endpoint sandbox cap | Re-run bootstrap with `--skip-endpoint` |
| `Limit exceeded on dimensional spend monitor` | 1-DIMENSIONAL-monitor account cap | Already handled — script reuses `Default-Services-Monitor` |
| `Daily or weekly frequencies only support Email` | Cost Anomaly subscription frequency | Already fixed — script uses IMMEDIATE |
| `Unknown parameter ... "Offset"` | Console-only alarm field | Already fixed — alarm uses `ANOMALY_DETECTION_BAND` |
| `Should NOT have more than 4 items` | Malformed dashboard metric tuple | Already fixed — current JSON is valid |
| `accelya-dlq-replayer-<learner> → MISSING` | Day-5 ref handler never deployed before | Bootstrap script now deploys it in STAGE 7 |
| `ValidationException ... NumberOfPolicyVersions` | IAM 5-version cap hit | Run bootstrap teardown then bootstrap; or manually `aws iam list-policy-versions` + delete oldest |
| `InvalidParameterValueException ... no permission for InvokeFunction` | IAM eventual consistency | Wait 15s; re-run the failed step |
| `ThrottlingException` from Bedrock | Throttle (rare at lab volume) | Reduce SAMPLE_RATE env on bedrock_enrich from 10 to 5 |

## Notes for Cascade

- **NEVER** skip steps. If the user says "just do the Day-10 deploy", run
  Steps 3 → 4 first to ensure the 10 Lambdas exist.
- **NEVER** invent learner names. Always prompt the user; reject invalid names.
- **ALWAYS** read the `bootstrap_day10.sh` summary table at end. If Lambda count
  is < 10, do not proceed to Step 6.
- **ALWAYS** preserve the same `$LEARNER` across the whole workflow. If the user
  opens a new terminal between steps, the env is lost — re-export from Step 1.
- **NEVER** delete a SageMaker endpoint that doesn't have the user's learner
  suffix. Endpoints from other learners are NOT yours to clean up.
- **VERIFY** every step's check before reporting success.
