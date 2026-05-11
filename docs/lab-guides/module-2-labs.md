# Module 2 — Lab Guides (Standalone Reference)

> The Day 2 deck has these labs on slides 20–28; this file is your standalone reference if you're working ahead, catching up, or stuck offline.

---

## Day 2 prerequisites (working from Day 1)

Before 09:00:

```bash
# 1. Update your local repo
cd accelya-agentic-aws
git pull origin main

# 2. Make your Day 2 branch
git checkout -b module-2-<your-name>

# 3. Re-verify AWS access
aws sts get-caller-identity --region ap-south-1
# Expected: your accelya-learner-<name> ARN (or federated role ARN)
```

If `aws sts get-caller-identity` fails, fix it before lab time. Day 2 has zero time slack for credential debugging.

---

## Lab 1 — IAM verification (30 min, solo)

**Deliverable:** `docs/m2-iam-verification.md` committed to your branch.

### Steps

```bash
# 1. Confirm identity
aws sts get-caller-identity --region ap-south-1
# Expected: JSON with Account, Arn, UserId. Arn ends in your accelya-learner-<name>.

# 2. Read identity + permission boundary
aws iam get-user --user-name accelya-learner-<your-name>
# Expected: JSON shows PermissionsBoundary attribute pointing at accelya-program-boundary.
#
# If you get NoSuchEntity (sandbox issues a federated role, not an IAM user):
ROLE_NAME=$(aws sts get-caller-identity --query 'Arn' --output text | awk -F'/' '{print $(NF-1)}')
aws iam get-role --role-name "$ROLE_NAME"
aws iam list-attached-role-policies --role-name "$ROLE_NAME"

# 3. Probe an ALLOWED action — should succeed
aws s3 ls s3://accelya-airline-data-ap-south-1/raw/ --region ap-south-1
# Expected: subfolders AI/, BA/, EK/, LH/, SQ/ — synthetic airlines.

# 4. Probe a DENIED action — should fail with AccessDeniedException
aws iam create-user --user-name should-fail
# Expected: AccessDeniedException (boundary blocks IAM writes).
# Note: IAM is global — no --region argument.
```

### Document your findings

`docs/m2-iam-verification.md` should contain:
- Your IAM identity ARN (redact account number)
- The PermissionsBoundary name
- One allowed action (with command + first 5 lines of output)
- One denied action (with command + error message captured)
- One sentence on what the boundary does (in your own words)

### Common gotchas

- **NoSuchEntity on get-user** — see step 2 fallback. Federated/assumed-role identities don't have an IAM user; use `get-role`.
- **`iam:CreateUser` succeeds** — STOP. Tell the trainer. The boundary isn't attached; sandbox is misconfigured.
- **`raw/` is empty** — wait 30s and retry. If still empty, the trainer hasn't seeded data yet.

---

## Lab 2 — S3 zone exploration (45 min, pairs)

**Deliverable:** `docs/m2-s3-layout.md` committed to your branch.

**⚠ Critical:** in step 3, upload to `learner-sandbox/<your-name>/raw-staging/`, **NOT** `raw/<your-name>/`. Uploading to `raw/<your-name>/` fires the Lab 3 Lambda prematurely.

### Steps

```bash
# 1. List the four-zone bucket layout
aws s3 ls s3://accelya-airline-data-ap-south-1/ --region ap-south-1
# Expected: raw/, validated/, curated/, quarantine/ (plus learner-sandbox/, models/)

# 2. Count raw objects per airline
aws s3 ls s3://accelya-airline-data-ap-south-1/raw/AI/ --recursive \
  --summarize --region ap-south-1 | tail -2
# Expected: Total Objects + Total Size print.

# 3. Stage your synthetic file (STAGING, NOT raw/)
aws s3 cp /data/synth/ticket-issues-AI-2026-05-05.json \
  s3://accelya-airline-data-ap-south-1/learner-sandbox/<your-name>/raw-staging/2026/05/05/ \
  --region ap-south-1
# Expected: "upload: ./ticket-issues-AI-2026-05-05.json to s3://..."

# 4. Verify your prefix
aws s3 ls s3://accelya-airline-data-ap-south-1/learner-sandbox/<your-name>/raw-staging/ \
  --recursive --human-readable --region ap-south-1
# Expected: one file with correct size and recent timestamp.

# 5. Commit your layout doc
git add docs/m2-s3-layout.md
git commit -m "m2: s3 layout documented"
git push origin module-2-<your-name>
```

### Document the layout

`docs/m2-s3-layout.md` should contain:
- A diagram (ASCII art or list) of all 4 zones (plus learner-sandbox, models)
- Per zone: who writes, what format (JSON/JSONL/Parquet), retention policy
- Where the trigger boundary is (`raw/<learner>/` fires the Lab 3 Lambda)
- A note on why Lab 2 stages to `learner-sandbox/...raw-staging/` instead of `raw/`

### Common gotchas

- **Upload to `raw/` instead of `learner-sandbox/...raw-staging/`** — this fires Lab 3's Lambda prematurely. If you do this by mistake, tell the trainer and delete the file before Lab 3.
- **Upload AccessDenied** — your prefix path is wrong. Must include `<your-name>/` (your IAM identifier).
- **`aws s3 cp` from `/data/synth/` fails** — the file is in your starter repo at `data/synthetic_ticket_issues.json`. Adjust the path.

---

## Lab 3 — Deploy validator Lambda (60 min, pairs)

**Deliverable:** running Lambda + `HITL_REVIEW.md` filled.

The Lambda function `accelya-m2-validator-<your-name>` is **pre-provisioned by the trainer**. You package and push code via `update-function-code`. The S3 trigger is pre-wired to `raw/<learner>/`.

### Steps

```bash
# 1. Package the function
cd src/validator && zip -j /tmp/validator.zip handler.py && cd -
ls -la /tmp/validator.zip
# Expected: ~2-5 KB, contains handler.py at the zip root.

# 2. Update code on the pre-created function
aws lambda update-function-code \
  --function-name accelya-m2-validator-<your-name> \
  --zip-file fileb:///tmp/validator.zip \
  --region ap-south-1
# Expected: LastUpdateStatus shows InProgress or Successful.

# 2a. WAIT for the update to complete (this step is critical)
aws lambda wait function-updated-v2 \
  --function-name accelya-m2-validator-<your-name> \
  --region ap-south-1
# (No output. Returns when LastUpdateStatus = Successful.)

# 3. Trigger by dropping a file into raw/<your-name>/ — the trigger zone
aws s3 cp /data/synth/ticket-issues-AI-2026-05-05.json \
  s3://accelya-airline-data-ap-south-1/raw/<your-name>/2026/05/05/ \
  --region ap-south-1
# This is the FIRST upload into raw/<your-name>/. Within ~5s:
# - validated/<your-name>/.../ticket-issues-AI-2026-05-05.json appears (494 records)
# - quarantine/<your-name>/.../ticket-issues-AI-2026-05-05.json appears (6 records)

# 4. Tail the structured logs
aws logs tail /aws/lambda/accelya-m2-validator-<your-name> \
  --follow --format short --region ap-south-1
# Expected: JSON lines with "event":"received" then "event":"validated".
# Note the corr_id for step 5.

# 5. Find the full invocation in CloudWatch Insights
# Cross-platform UTC epoch seconds:
START=$(python3 -c 'import time; print(int(time.time()-600))')
END=$(python3 -c 'import time; print(int(time.time()))')

aws logs start-query \
  --log-group-name /aws/lambda/accelya-m2-validator-<your-name> \
  --start-time $START --end-time $END \
  --query-string 'fields @timestamp, event, records_good, records_bad | filter corr_id = "<paste-id-here>"' \
  --region ap-south-1
# Returns QueryId. Then poll:
aws logs get-query-results --query-id <QueryId> --region ap-south-1
# Repeat until Status: Complete.
```

### Verify the outcome

```bash
# Validated rows
aws s3 ls s3://accelya-airline-data-ap-south-1/validated/<your-name>/2026/05/05/ \
  --recursive --human-readable --region ap-south-1
# Expected: 1 file, ~480 KB (494 records).

# Quarantined rows
aws s3 ls s3://accelya-airline-data-ap-south-1/quarantine/<your-name>/2026/05/05/ \
  --recursive --human-readable --region ap-south-1
# Expected: 1 file, ~5-10 KB (6 records).
```

### Score the Lambda on the HITL checklist

Fill `reviews/HITL_REVIEW-m2-validator.md` with 5 dims scored 0-3. The trainer-provided handler (`src/validator/handler.py`) is annotated against the 5 dims — use those annotations as anchors. Expected score: ~13-14/15 PASS.

Then update the root `HITL_REVIEW.md` Module 2 section with the final score + verdict.

### Common gotchas

- **`update-function-code` succeeded but the OLD code ran** — you didn't wait for the update. Always run `aws lambda wait function-updated-v2` between update and trigger.
- **Step 3 doesn't fire the Lambda** — three checks: (a) Did you upload to `raw/<your-name>/` exactly? Not `raw/AI/` (cohort-shared) and not `learner-sandbox/`. (b) Did you wait for update? (c) Look at `aws logs tail` — any entry?
- **`aws logs tail` shows nothing** — Lambda may not have fired. Check `aws lambda get-function --function-name <fn> --query Configuration.LastUpdateStatus` — should be `Successful`.
- **`corr_id` not in the log line** — look for `aws_request_id` (the Lambda context key) in the JSON. That IS the corr_id; some log lines may not include it if emit() wasn't called.
- **Insights returns empty results** — wait 30s. CloudWatch Logs ingestion has up to 5 min lag.
- **Insights query has Status: Failed** — your query syntax is off. Test in the AWS console first.

---

## End-of-module cleanup

```bash
# Empty your S3 prefixes (everything you wrote today)
for zone in raw validated quarantine; do
  aws s3 rm s3://accelya-airline-data-ap-south-1/$zone/<your-name>/ \
    --recursive --region ap-south-1
done

# Empty the staging area too
aws s3 rm s3://accelya-airline-data-ap-south-1/learner-sandbox/<your-name>/raw-staging/ \
  --recursive --region ap-south-1

# Verify
for zone in raw validated quarantine learner-sandbox; do
  echo "=== $zone ==="
  aws s3 ls s3://accelya-airline-data-ap-south-1/$zone/<your-name>/ --recursive --region ap-south-1
done
# All should be empty.
```

**Do NOT delete the Lambda function** — it's pre-provisioned by the trainer and stays. The Day 3 conceptual work doesn't touch it; Days 4-12 build new Lambdas alongside.

```bash
# Commit + push + open PR
git add docs/m2-iam-verification.md docs/m2-s3-layout.md \
        src/validator/handler.py reviews/HITL_REVIEW-m2-validator.md HITL_REVIEW.md
git commit -m "module-2: complete"
git push origin module-2-<your-name>

# Open PR on GitHub
echo "Open PR at: https://github.com/jaisingh-builds/accelya-agentic-aws/compare/main...module-2-<your-name>"
```

---

## Day 2 in numbers

| Metric | Value |
|---|---|
| New Lambdas deployed | 1 (validator) |
| Lambda count cumulative | 1 of 10 |
| Bedrock invocations | 0 today; cumulative ~2-5 of 50 |
| S3 zones touched | `raw/<name>/`, `validated/<name>/`, `quarantine/<name>/`, `learner-sandbox/<name>/raw-staging/` |
| Artefacts in branch | 4 (IAM verification, S3 layout, validator code, HITL review) |
| PR commits | 3 (Lab 1 + Lab 2 + Lab 3) |

---

## What's coming on Day 3

Module 3 — Agentic AI Foundations for Engineering Teams.
You'll write your first `.windsurfrules` v1, learn the 5-section prompt anatomy applied to code generation, and do the weak-vs-strong validator critique (Lab 3 is the signature). Lots of Cascade work; very little AWS provisioning.

Bring today's branch with you — Day 3 reads from your `src/validator/handler.py` as the reference shape every future Lambda follows.

---

*See `Day2_Module2_AWS_Fundamentals.pptx` slides 20-28 for the deck's full visual treatment.*
