---
description: Daily-reset bootstrap for Day 11 labs. Cascade walks the learner through bringing up the Day-10 stack PLUS GitHub OIDC + IAM role + foundation stack via SAM.
---

# Day 11 Bootstrap (Cascade-orchestrated)

This workflow extends `/day10-bootstrap` with Day-11 prerequisites: GitHub
Actions OIDC identity provider in AWS, scoped IAM role for GitHub Actions
to assume via web identity, and the foundation stack (SAM-deployed,
stateful resources with `DeletionPolicy: Retain`).

## What you need before starting

- Day-10 bootstrap has run (or runs as part of this workflow)
- `sam` CLI ≥ 1.115 installed
- `gh` CLI ≥ 2.40 installed and authenticated to GitHub (`gh auth login`)
- Your fork pushed to GitHub (default: `jaisingh-builds/accelya-agentic-aws`)
- AWS credentials exported in this terminal

## Step 1 — Set learner suffix + GitHub repo

Ask the user for their learner name. Validate `^[a-z][a-z0-9-]*$`.
Then confirm GitHub owner + repo (defaults shown).

```bash
export LEARNER=<learner-from-user>
export AWS_REGION=ap-south-1
export GITHUB_OWNER=${GITHUB_OWNER:-jaisingh-builds}
export GITHUB_REPO=${GITHUB_REPO:-accelya-agentic-aws}
echo "LEARNER=$LEARNER ; GITHUB_OWNER=$GITHUB_OWNER ; GITHUB_REPO=$GITHUB_REPO"
```

**Verify:** all three env vars echo non-empty values. If the user's fork lives
under a different owner, override `GITHUB_OWNER` before running Step 2.

## Step 2 — Run the combined Day-10 + Day-11 bootstrap

```bash
cd /path/to/accelya-agentic-aws/starter-repo
bash scripts/bootstrap_day10.sh $LEARNER --day=11
```

**Verify (must all pass):**
- Final STAGE F summary shows `Lambda count: 10 / 10`
- All 10 Day-9 Lambdas Active
- STAGE 14 reports either "Provider already exists" or "Created: arn:aws:iam::...:oidc-provider/token.actions.githubusercontent.com"
- STAGE 15 reports "Created role" or "Updated trust policy (owner=... repo=...)"
- STAGE 16 reports "Foundation stack created" or "already CREATE_COMPLETE"
- Summary table shows OIDC role + Foundation stack with status

**If STAGE 16 says `sam CLI missing`:** install with:
```bash
brew tap aws/tap && brew install aws-sam-cli      # macOS
# OR
pip install aws-sam-cli                            # Linux/WSL
```

**If STAGE 14 says `OIDC provider create failed`:** another learner in the
shared sandbox may have just been creating it. Re-run from Step 2 — second
run will find it via the existing-check.

## Step 3 — Promote `.windsurfrules` to v8

```bash
cp docs/.windsurfrules-v8.template .windsurfrules
git add .windsurfrules prompts/v14_deploy.txt prompts/cascade-mr-review.txt
git commit -m "feat(m11): promote .windsurfrules to v8 (DEPLOY CONTEXT)"

head -2 .windsurfrules           # expected: '# .windsurfrules — v8 ...'
```

**Why this matters:** v8 adds the DEPLOY CONTEXT block (14th prompt layer)
plus the 4 new Day-11 entries in the KNOWN-ERROR REGISTER. Cascade reads
this on every prompt from now on.

## Step 4 — Set the OIDC role ARN as a GitHub Actions secret

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/accelya-github-oidc-${LEARNER}"
GH_REPO="${GITHUB_OWNER}/${GITHUB_REPO}"

# Push current branch to GitHub (must run from inside the starter-repo directory
# where .git lives — `git push` needs the git dir, not the project root above it)
cd /path/to/accelya-agentic-aws/starter-repo
git push -u origin module-11-$LEARNER

# Set the OIDC role ARN as a repo secret — pass -R explicitly so it works
# regardless of $PWD (gh sub-commands try to auto-detect from .git otherwise)
gh secret set AWS_OIDC_ROLE_ARN -R "$GH_REPO" -b "$ROLE_ARN"

# Verify it's set
gh secret list -R "$GH_REPO" | grep AWS_OIDC_ROLE_ARN
```

**CRITICAL VERIFY — zero static AWS keys in secrets OR variables:**
```bash
{ gh secret list   -R "$GH_REPO" --json name -q '.[].name';
  gh variable list -R "$GH_REPO" --json name -q '.[].name'; } | \
  grep -iE '^aws_(access_key_id|secret_access_key|session_token)$'
```
**Expected output:** EMPTY. If anything prints, those entries MUST be deleted before continuing. Day-11 contract forbids static keys.

## Step 5 — App stack deploy (Lab 1 Sub-step D)

```bash
cd infra
sam build -t template-app.yaml
sam deploy -t template-app.yaml \
  --stack-name accelya-app-$LEARNER \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameter-overrides Learner=$LEARNER \
  --no-confirm-changeset \
  --tags programme=accelya owner=$LEARNER environment=lab
cd ..
```

**Verify:**
```bash
aws cloudformation describe-stacks \
  --stack-name accelya-app-$LEARNER --region $AWS_REGION \
  --query 'Stacks[0].StackStatus' --output text
# Expected: CREATE_COMPLETE

aws lambda list-functions --region $AWS_REGION \
  --query "length(Functions[?contains(FunctionName,'-$LEARNER')])"
# Expected: 11
```

## Step 6 — You are ready for Labs 2 + 3

Tell the user:

> ✅ Day-11 environment is up (GitHub-primary path).
>
> Foundation + App stacks `CREATE_COMPLETE`. 11 Lambdas Active.
> GitHub OIDC role wired. Zero static AWS keys in secrets/variables.
>
> Open `starter-repo/docs/lab-guides/module-11-labs.md` and proceed:
> - Lab 1 already done (Sub-steps A-D)
> - Lab 2 (45 min): open a draft PR and watch `.github/workflows/sandbox-deploy.yml` run green
> - Lab 3 (45 min): `gh pr diff` → Cascade MR-review → auto-rollback demo
>
> GitLab alternative documented at `docs/ci-reference/github-vs-gitlab.md` —
> reference only; the runnable lab path is GitHub.
>
> At end of day:
> ```bash
> gh pr close <pr-number>
> bash scripts/bootstrap_day10.sh $LEARNER --teardown
> ```
> The app stack auto-deletes on PR close via `.github/workflows/sandbox-cleanup.yml`.
> Foundation stack PERSISTS (Retain-policy). Sandbox reset overnight wipes both regardless.

## Troubleshooting cheat sheet

| Error fragment | Fix |
|---|---|
| `--day=11 not recognised` | Old bootstrap script; `git pull --ff-only` |
| `sam CLI missing` | `brew install aws-sam-cli` or `pip install aws-sam-cli` |
| `OIDC provider create failed` | Concurrent creation by another learner; re-run (idempotent) |
| Foundation stack `CREATE_FAILED` | Check `describe-stack-events`; usually IAM eventual consistency — re-run after 30s |
| Foundation stack `ROLLBACK_COMPLETE` | Delete the stack manually before re-run: `aws cloudformation delete-stack --stack-name accelya-foundation-$LEARNER` |
| App stack `Stack ... cannot be updated` | Concurrent deploy in flight; wait for it; retry |
| Step 4 `gh not found` | Install gh: `brew install gh` or download from github.com/cli/cli |
| Step 4 grep finds static AWS_ keys | Delete them: `gh secret delete AWS_ACCESS_KEY_ID` etc. Day-11 contract forbids these. |
| GitHub Actions: `InvalidIdentityToken: Token has invalid audience` | `aws-actions/configure-aws-credentials@v4` defaults aud=sts.amazonaws.com — don't override with `audience:` unless your trust policy matches |
| GitHub Actions: `AccessDenied` on AssumeRoleWithWebIdentity | Trust policy sub doesn't match — inspect the failed run's logs for the JWT's sub claim; update `infra/oidc-trust-policy.json` accordingly |

## Notes for Cascade

- **NEVER** skip Step 4's grep check for static AWS keys. The Day-11 contract
  forbids them entirely.
- **NEVER** invent learner names or GitHub owner/repo. Always prompt the user.
- **ALWAYS** verify Lambda count == 11 before declaring success.
- **NEVER** delete a foundation stack from this workflow. If teardown is
  needed, point the user at `trainer-deliverables/57_foundation_teardown.md`.
- **ALWAYS** preserve `$LEARNER` + `$GITHUB_OWNER` + `$GITHUB_REPO` across steps.
- **NEVER** use `${{ secrets.AWS_ACCESS_KEY_ID }}` in any workflow. Only
  `${{ secrets.AWS_OIDC_ROLE_ARN }}` is acceptable as a secret reference.
