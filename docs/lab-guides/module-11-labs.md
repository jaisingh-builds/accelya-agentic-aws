# Module 11 — Lab Guides (Standalone Reference)

> The Day 11 deck has these labs on slides 22-32; this file is your standalone reference.

---

## 🌅 Day 11 morning — daily-reset bootstrap

> **Read this first.** Pluralsight sandbox resets every night. Day 11 needs the
> Day-10 stack PLUS GitHub OIDC + IAM role + foundation stack. The bootstrap
> handles all of it.
>
> **CI platform:** GitHub Actions is the runnable lab path (starter-repo lives
> at `github.com/jaisingh-builds/accelya-agentic-aws`). GitLab is documented as
> a reference appendix at `docs/ci-reference/github-vs-gitlab.md` for corps
> standardised on GitLab.

### Option A — Cascade-orchestrated (recommended)

In Windsurf:
```
/day11-bootstrap
```
Cascade reads `.windsurf/workflows/day11-bootstrap.md`, prompts for your learner
name + GitHub owner/repo, runs every step. ~12-15 minutes cold.

### Option B — Manual one-paste

```bash
cd accelya-agentic-aws/starter-repo
git checkout main && git pull --ff-only
git checkout -b module-11-<your-name>

export LEARNER=<your-name>                          # lowercase, alphanumeric+hyphen
export AWS_REGION=ap-south-1
export GITHUB_OWNER=${GITHUB_OWNER:-jaisingh-builds}   # override if your fork is elsewhere
export GITHUB_REPO=${GITHUB_REPO:-accelya-agentic-aws}

# Bootstrap Day-10 stack + Day-11 prerequisites
bash scripts/bootstrap_day10.sh $LEARNER --day=11
```

The `--day=11` flag adds, on top of the Day-10 stack:
- GitHub Actions OIDC identity provider in AWS (one per account; idempotent)
- IAM role `accelya-github-oidc-<learner>` with scoped trust policy
- Foundation stack `accelya-foundation-<learner>` via SAM
- Outputs all the resource ARNs you need for Lab 1

### What the bootstrap creates (Day 11 deltas)

| Stage | Resource | Why Day 11 needs it |
|---|---|---|
| 14 | OIDC provider `https://token.actions.githubusercontent.com` | GitHub Actions authenticates without static AWS keys |
| 15 | IAM role `accelya-github-oidc-<learner>` | Role that GitHub Actions assumes via web identity (sub scoped to `repo:<owner>/<repo>`) |
| 16 | Foundation stack `accelya-foundation-<learner>` | DDB + Kinesis + SQS + SNS with `DeletionPolicy: Retain` |

### Promote `.windsurfrules` to v8 (after bootstrap)

```bash
cp docs/.windsurfrules-v8.template .windsurfrules
git add .windsurfrules prompts/v14_deploy.txt prompts/cascade-mr-review.txt
git commit -m "feat(m11): promote .windsurfrules to v8 (DEPLOY CONTEXT)"

head -2 .windsurfrules           # expected: '# .windsurfrules — v8 ...'
```

v8 adds the **DEPLOY CONTEXT** block (14th prompt layer). Cascade reads it on
every prompt from now on.

### GitHub repo setup (one-time per session)

```bash
# Make sure gh is authenticated
gh auth status

# CRITICAL: gh sub-commands like `secret set` and `variable list` auto-detect
# the repo from $PWD's .git. The starter-repo lives inside the project folder
# you cloned, so cd INTO it first — OR pass `-R <owner>/<repo>` explicitly
# to every command. We'll use -R below to be safe regardless of $PWD.
GH_REPO="${GITHUB_OWNER}/${GITHUB_REPO}"   # e.g. jaisingh-builds/accelya-agentic-aws

# Push your branch (creates the remote-tracking ref) — must run inside the git repo
git push -u origin module-11-$LEARNER

# Set the OIDC role ARN as a repo secret (mask in logs even though it's just an ARN)
gh secret set AWS_OIDC_ROLE_ARN -R "$GH_REPO" -b \
  "arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/accelya-github-oidc-$LEARNER"

# Verify NO static AWS keys live in repo secrets OR variables (Day-11 invariant)
{ gh secret list   -R "$GH_REPO" --json name -q '.[].name';
  gh variable list -R "$GH_REPO" --json name -q '.[].name'; } | \
  grep -iE '^aws_(access_key_id|secret_access_key|session_token)$'
# Expected: NO output. If anything prints, delete with:
#   gh secret delete AWS_ACCESS_KEY_ID -R "$GH_REPO"     (etc.)
```

### End-of-day teardown (don't skip)

```bash
# Close or merge your PR — sandbox-cleanup.yml auto-deletes the app stack
gh pr close <pr-number>     # or `gh pr merge <pr-number>`

# Wait ~1-2 min for cleanup workflow, then verify stack gone
aws cloudformation list-stacks --region $AWS_REGION \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query "StackSummaries[?contains(StackName,'accelya-app-pr-')].StackName" --output text
# Expected: empty

# Bootstrap teardown (covers Day-10 + Day-11 — foundation stack PRESERVED)
bash scripts/bootstrap_day10.sh $LEARNER --teardown
```

Sandbox resets overnight anyway, but cleanly closing the PR triggers
sandbox-cleanup.yml which frees up the per-PR app-stack name.

---

## Lab 1 (45 min, pairs) — Convert D9 stack to SAM; deploy via OIDC

**Goal.** Replace 8 hand-rolled `aws lambda ...` scripts with one `sam deploy`.
Foundation stack (stateful, retained) + app stack (ephemeral, redeployable per PR).

### Sub-step 0 — Migration gate (TRAINER ONLY)

> Skip this step. Your daily-reset sandbox has nothing to migrate from.
> The trainer demonstrates this on their persistent account:
>
> ```bash
> # Trainer-only — snapshots all manual Lambdas, deletes them, verifies count=0
> bash scripts/preflight-lambda-cap.sh trainer --delete-manual
> ```
>
> Trainer watches the snapshot files appear in `reviews/m11-pre-migration/`
> then runs `sam deploy` which recreates everything from the SAM template.
> This is the only path you'd take in production migrating from manual
> deploys to IaC.

### Sub-step A — Cascade authors `template-foundation.yaml`

Open a fresh Cascade chat. Ask:

> *"Scaffold `infra/template-foundation.yaml` per the DEPLOY CONTEXT block in
> `.windsurfrules` v8. Include DDB stream_seen_keys table, Kinesis stream
> cancellation-events, SQS stream-dlq, SQS model-review-queue, SNS
> accelya-alarms, SNS accelya-dlq-escalation. Every stateful resource MUST
> have DeletionPolicy: Retain AND UpdateReplacePolicy: Retain. Export every
> ARN/URL as a stack Output for cross-stack import."*

The repo already ships a reference at `infra/template-foundation.yaml`. Your
Cascade output should match within ~10% diff. If Cascade omits the SNS topic
policy that allows `costalerts.amazonaws.com:sns:Publish`, **v8 didn't pick up**
(that's part of the OBSERVABILITY CONTEXT from D10 carried into v8). Verify
with `head -2 .windsurfrules`.

### Sub-step B — Deploy foundation stack

```bash
cd infra
sam validate -t template-foundation.yaml
sam deploy -t template-foundation.yaml \
  --stack-name accelya-foundation-$LEARNER \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides Learner=$LEARNER \
  --no-confirm-changeset \
  --tags programme=accelya owner=$LEARNER environment=lab
cd ..

# Verify
aws cloudformation describe-stacks \
  --stack-name accelya-foundation-$LEARNER --region $AWS_REGION \
  --query 'Stacks[0].StackStatus' --output text
# Expected: CREATE_COMPLETE (or UPDATE_COMPLETE if re-run)

# Capture outputs (used by app stack)
aws cloudformation describe-stacks \
  --stack-name accelya-foundation-$LEARNER --region $AWS_REGION \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
```

Wait ~3 minutes for stack creation. Don't proceed until status shows
`CREATE_COMPLETE`.

### Sub-step C — Cascade authors `template-app.yaml`

Ask Cascade:

> *"Scaffold `infra/template-app.yaml` per the DEPLOY CONTEXT block. Include
> all 11 Lambdas (validator, lander, chunker, dlq-replayer, etl-json-to-parquet,
> producer, consumer, bedrock-enrich, persist-enriched, predict-cancel-risk,
> pretraffic-hook). Every Lambda EXCEPT pretraffic-hook must have:
> AutoPublishAlias: live, DeploymentPreference with PreTraffic hook + 2 alarms.
> Every Lambda must have explicit AWS::Logs::LogGroup with DependsOn +
> LoggingConfig.LogGroup. Reference foundation stack outputs via !ImportValue
> accelya-foundation-${Learner}-<OutputName>. Single PipelineExecutionRole shared
> across all 11. 3 alarms (iterator-age, bedrock-throttle, confidence-drift)
> defined in this stack."*

Reference: `infra/template-app.yaml` in the repo (canonical pattern; only 2 of
the 11 Lambdas are fully written for readability — the others follow the same
skeleton). Cascade with v8 expands the rest correctly.

### Sub-step D — Deploy app stack

```bash
cd infra
sam build -t template-app.yaml
sam validate -t template-app.yaml
sam deploy -t template-app.yaml \
  --stack-name accelya-app-$LEARNER \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameter-overrides Learner=$LEARNER \
  --no-confirm-changeset \
  --tags programme=accelya owner=$LEARNER environment=lab
cd ..

# Verify
aws cloudformation describe-stacks \
  --stack-name accelya-app-$LEARNER --region $AWS_REGION \
  --query 'Stacks[0].StackStatus' --output text
# Expected: CREATE_COMPLETE (takes ~4 minutes)

# Lambda count
aws lambda list-functions --region $AWS_REGION \
  --query "length(Functions[?contains(FunctionName,'-$LEARNER')])"
# Expected: 11
```

### Lab 1 checkpoint (deck slide 25)

| Check | Command | Expected |
|---|---|---|
| Foundation stack CREATE_COMPLETE | `aws cloudformation describe-stacks --stack-name accelya-foundation-$LEARNER` | CREATE_COMPLETE |
| App stack CREATE_COMPLETE | `aws cloudformation describe-stacks --stack-name accelya-app-$LEARNER` | CREATE_COMPLETE |
| 11 Lambdas Active | `aws lambda list-functions ... \| length` | 11 |
| All Lambdas have alias `live` | `aws lambda list-aliases --function-name accelya-predict-cancel-risk-$LEARNER` | 1 alias `live` |
| Foundation outputs imported by app | `aws cloudformation list-exports \| grep accelya-foundation-$LEARNER` | ≥ 8 exports |
| `/reviews/m11-sam-deploy.md` exists | `git status` | committed |

---

## Lab 2 (45 min, pairs) — `.github/workflows/sandbox-deploy.yml` + OIDC + scanners

**Goal.** Replace `bash scripts/deploy_m*.sh` with a GitHub Actions pipeline
that runs scanners, deploys to a sandbox stack per PR, runs an integration
test, and auto-cleans on PR close.

### Step 1 — OIDC identity provider + IAM role (already done by bootstrap)

The bootstrap created both. Verify:

```bash
# OIDC provider
aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?contains(Arn,'token.actions.githubusercontent.com')].Arn" \
  --output text
# Expected: arn:aws:iam::<acct>:oidc-provider/token.actions.githubusercontent.com

# Role + trust scope (no wildcards)
aws iam get-role --role-name accelya-github-oidc-$LEARNER \
  --query 'AssumeRolePolicyDocument.Statement[].Condition' --output json
# Expected: scoped StringEquals/StringLike on token.actions.githubusercontent.com:sub
#           — repo:<owner>/<repo>:ref:refs/heads/<branch-glob> OR :pull_request
#           NEVER 'repo:*' or '*'
```

If MISSING: re-run `bash scripts/bootstrap_day10.sh $LEARNER --day=11`.

### Step 2 — `.github/workflows/sandbox-deploy.yml`

The repo ships a complete `.github/workflows/sandbox-deploy.yml`. Open it:
```bash
cat .github/workflows/sandbox-deploy.yml
```

Key blocks to understand:
- **`on: pull_request` + `on: push: branches: [main]`**: triggers — sandbox per PR; lint also runs on main push
- **`permissions: id-token: write`**: MANDATORY toggle that lets GitHub mint the OIDC JWT
- **`concurrency:` group + `cancel-in-progress: true`**: cancels stale runs when a new commit lands on the same PR
- **`aws-actions/configure-aws-credentials@v4`**: the OIDC assume-role helper — pass `role-to-assume: ${{ secrets.AWS_OIDC_ROLE_ARN }}` and the audience defaults to `sts.amazonaws.com`
- **4 lint jobs in parallel**: bandit + semgrep + cfn-lint + cfn-nag (NOT tflint — that's Terraform-only)
- **`preflight-lambda-cap`**: hard cap check before deploy-sandbox
- **`deploy-sandbox`**: SAM deploy; declares `environment: name: pr-${{ github.event.pull_request.number }}`
- **`integration-test`**: runs `tests/integration_test.py` against the sandbox stack
- **`.github/workflows/sandbox-cleanup.yml`** (separate file): triggered on `pull_request: types: [closed]`; deletes the app stack

### Step 3 — Open a draft PR

```bash
git add .github/workflows/ infra/ scripts/
git commit -m "feat(m11): SAM templates + GitHub Actions + OIDC"
git push -u origin module-11-$LEARNER

# Create draft PR
gh pr create --title "Day-11 SAM + CI/CD" --draft \
  --body "Lab 2 — pipeline smoke test"

# Watch the workflow run
gh run watch
```

### Step 4 — Pipeline smoke (must turn green)

Watch the 4 lint jobs run in parallel (~30s). Watch the preflight job pass.
Watch `deploy-sandbox` create stack `accelya-app-pr-<number>` (~5 min).
Watch `integration-test` send a booking + cancellation event through the
pipeline and verify both reached settlement (~2 min).

If any job fails, `gh run view --log-failed` shows the log; common issues
in the gotchas section below.

### Step 5 — Cleanup smoke (close the PR)

```bash
# Get the PR number
PR_NUM=$(gh pr list --state open --head module-11-$LEARNER --json number -q '.[0].number')
gh pr close $PR_NUM

# sandbox-cleanup.yml triggers on `pull_request: closed`; watch it run
gh run watch

# After ~2 min, verify the stack is gone
aws cloudformation describe-stacks \
  --stack-name accelya-app-pr-${PR_NUM} \
  --region $AWS_REGION 2>&1 | grep -E 'does not exist|DELETE_COMPLETE'
# Expected: "Stack ... does not exist" OR DELETE_COMPLETE
```

### Step 6 — Zero static AWS keys (non-negotiable invariant)

```bash
{ gh secret list --json name -q '.[].name'; gh variable list --json name -q '.[].name'; } | \
  grep -iE '^aws_(access_key_id|secret_access_key|session_token)$'
# Expected: NO OUTPUT
```

If this prints any matches, you broke the OIDC contract. Delete those
entries (`gh secret delete <name>` / `gh variable delete <name>`) before
continuing. Only `AWS_OIDC_ROLE_ARN` is acceptable as a secret.

### Lab 2 checkpoint (deck slide 29)

| Check | Command | Expected |
|---|---|---|
| OIDC provider exists | `aws iam list-open-id-connect-providers` | token.actions.githubusercontent.com listed |
| Role scoped (no wildcards) | `aws iam get-role --role-name accelya-github-oidc-$LEARNER` | StringEquals/StringLike on `repo:<owner>/<repo>:...`, no `*` |
| Pipeline green end-to-end | `gh run view --json conclusion -q .conclusion` | `success` |
| Sandbox stack created | `aws cloudformation describe-stacks --stack-name accelya-app-pr-<num>` | CREATE_COMPLETE |
| PR close triggers cleanup | `gh pr close && gh run watch` | sandbox-cleanup.yml runs; stack gone |
| Zero AWS keys in secrets/variables | grep above | empty |
| `/reviews/m11-ci-pipeline.md` exists | `git status` | committed |

---

## Lab 3 (45 min, solo) — Cascade PR-review prompt + rollback demo

**Goal.** Use Cascade as a structured PR reviewer. Trigger the CodeDeploy
auto-rollback. Practise manual rollback via `update-alias`.

### Step 1 — Get a diff to review

If you're paired: grab your partner's branch diff.
If solo: use yesterday's tightened-IAM PR or any peer's PR.

```bash
gh pr diff <peer-pr-number> --patch > /tmp/pr.diff
wc -l /tmp/pr.diff
```

### Step 2 — Cascade PR review

Open a fresh Cascade chat in Windsurf. Paste the ENTIRE contents of
`prompts/cascade-mr-review.txt` as the SYSTEM prompt. Then paste the diff
as the USER message.

Cascade returns:
- 5 auto-fail red-flag checks (LITERAL grep output, not summarised)
- 9-dim rubric scores (each 0-3, total /27)
- Recommendation: APPROVE / REVIEW / BLOCK

**Critical check:** If Cascade says "no static AWS keys found" without
showing the literal grep, that's a violation. Reply "show the grep output
verbatim" and re-prompt.

### Step 3 — Post Cascade's response as PR comment

```bash
gh pr comment <peer-pr-number> -F /tmp/cascade-review.md
```

### Step 4 — Resolve at least one suggestion

Pick one finding from Cascade's review. Either:
- **Fix it**: commit the fix; push; comment "Fixed in <SHA>"
- **Push back**: explain why the finding is wrong/acceptable in the thread

### Step 5 — Auto-rollback demo (the headline)

Deliberately break one Lambda. Push. Watch CodeDeploy roll back.

```bash
# 1. Patch predict handler to raise on entry
cat > /tmp/break.py <<'PY'
import sys
src = open("src/predict/handler.py").read()
patched = src.replace(
    "def handler(event, context):",
    'def handler(event, context):\n    raise RuntimeError("intentional break for rollback demo")',
    1
)
open("src/predict/handler.py", "w").write(patched)
PY
python3 /tmp/break.py

# 2. Commit + push
git add src/predict/handler.py
git commit -m "DEMO: deliberately break predict for rollback test"
git push

# 3. Watch the pipeline. Deploy-sandbox will SUCCEED — sam deploy publishes
#    the new version. But CodeDeploy starts the linear traffic shift...
gh run watch

# 4. Send traffic to trigger the alarm (in a separate terminal)
for i in 1 2 3 4 5; do
  aws lambda invoke --function-name accelya-predict-cancel-risk-$LEARNER \
    --qualifier live --payload '{"booking_id":"BK-1","fare_amount":1000}' \
    --region $AWS_REGION /tmp/out-$i.json
done
# These invocations will fail (the new version raises immediately).
# CW's Lambda Errors metric spikes → if you wired the alarm correctly,
# CodeDeploy detects + rolls back within 1-2 min.

# 5. Watch CodeDeploy
aws deploy list-deployments --region $AWS_REGION \
  --query 'deployments[0]' --output text
DEPLOY_ID=<from above>
aws deploy get-deployment --deployment-id $DEPLOY_ID --region $AWS_REGION \
  --query 'deploymentInfo.{status:status,rollback:rollbackInfo}'

# Expected:
#   status: STOPPED (auto-rollback fired)
#   rollback: {rollbackTriggeringDeploymentId, rollbackMessage}
```

### Step 6 — Manual rollback (memorise this command)

```bash
# Find previous version
PREV_VERSION=$(aws lambda list-versions-by-function \
  --function-name accelya-predict-cancel-risk-$LEARNER \
  --region $AWS_REGION \
  --query 'Versions[-2].Version' --output text)
echo "PREV: $PREV_VERSION"

# Point alias at it
aws lambda update-alias \
  --function-name accelya-predict-cancel-risk-$LEARNER \
  --name live \
  --function-version $PREV_VERSION \
  --region $AWS_REGION

# Verify alias points at previous version
aws lambda get-alias \
  --function-name accelya-predict-cancel-risk-$LEARNER \
  --name live --region $AWS_REGION \
  --query 'FunctionVersion'
# Expected: $PREV_VERSION
```

### Step 7 — Revert the break + close the PR

```bash
git revert HEAD --no-edit
git push
gh pr close $PR_NUM    # or `gh pr merge $PR_NUM` if the team has a green build
```

### Lab 3 checkpoint (deck slide 32)

| Check | Evidence |
|---|---|
| Cascade ran the 5 grep checks literally | `/tmp/cascade-review.md` has each grep + output, not "looks clean" |
| At least one suggestion resolved (fix OR pushback) | PR thread shows a reply |
| Auto-rollback triggered | `aws deploy get-deployment $DEPLOY_ID` shows status STOPPED + rollback info |
| Manual rollback restored alias | `aws lambda get-alias ... live` shows $PREV_VERSION |
| `/reviews/m11-mr-review.md` exists | `git status` |

---

## Common gotchas

### Bootstrap-time

| Symptom | Cause | Fix |
|---|---|---|
| `--day=11` not recognised by bootstrap | Old bootstrap script | `git pull --ff-only` |
| OIDC provider create returns `EntityAlreadyExists` | Shared sandbox; another learner created it | Reuse it; bootstrap script handles this idempotently |
| Foundation stack CREATE_FAILED on Kinesis | Kinesis stream by same name already exists from manual create | Trainer-only: run migration gate. Learners: shouldn't happen (sandbox reset) |
| `sam deploy` returns `Stack ... is in ROLLBACK_COMPLETE state and can not be updated` | Previous CREATE failed mid-way | `aws cloudformation delete-stack`, then re-deploy |
| `sam build` fails on `requirements.txt` not found | CodeUri path wrong | Use `../src/<name>/` relative to infra/ |

### Lab-time

| Symptom | Cause | Fix |
|---|---|---|
| `InvalidIdentityToken: Token has invalid audience` | aud mismatch | `.github/workflows/sandbox-deploy.yml` `id_tokens.GITLAB_OIDC_TOKEN.aud` MUST be `sts.amazonaws.com` |
| `AccessDenied` on assume-role | Trust policy `sub` doesn't match GitHub's `sub` claim | Inspect the failed run with `gh run view --log` and look for the JWT's `sub` claim in the configure-aws-credentials step; update `infra/oidc-trust-policy.json` accordingly |
| `Lambda function ... already exists` | Stale Lambda from a previous CREATE that rolled back | `aws lambda delete-function`, retry |
| `Stack ... cannot be updated. Reason: not in a state that supports update` | Concurrent deploy in flight | Wait for current deploy; retry |
| `Sub: project_path:*` flagged by Cascade review | Wildcard OIDC sub | Replace with explicit `project_path:<group>/<project>:ref_type:branch:ref:<branch>` |
| `cfn-nag` warns W11 on xray:* | False positive — xray IS resource-agnostic at the AWS service level | Add suppression to `infra/cfn_nag/suppressions.yml` with rule ID + reason |
| CodeDeploy auto-rollback never fires | Alarm not associated with `DeploymentPreference.Alarms` | Add the alarm ref in the Lambda's DeploymentPreference block; redeploy |
| Manual rollback `update-alias` succeeds but the bug persists | The alias change took effect — clients caching old DNS? Lambda alias resolution is instant; if you see stale behavior, the new version was buggy too | Check Lambda logs for the alias's current version |

---

*Cross-reference: deck `Day11_Module11_EndToEnd_Integration.pptx` (37 slides). Trainer guide `trainer-deliverables/55_day11_trainer_study_guide.md`. Requirements `trainer-deliverables/53_day11_requirements_and_prep.md`.*
