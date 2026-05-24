# GitHub Actions vs GitLab CI — same pipeline, two engines

The Accelya Day-11 lab runs on **GitHub Actions** (`.github/workflows/sandbox-deploy.yml`).
This document is a reference appendix showing the equivalent GitLab CI configuration
(`docs/ci-reference/gitlab-ci-example.yml`) for learners whose corp uses GitLab.

Both pipelines do the same thing: lint → test → deploy-sandbox → integration-test,
with OIDC trust to AWS (no static keys) and sandbox-per-PR/MR auto-cleanup.

## Side-by-side concept map

| Concept | GitHub Actions | GitLab CI |
|---|---|---|
| Pipeline file | `.github/workflows/<name>.yml` | `.gitlab-ci.yml` |
| Stage grouping | `jobs:` + `needs:` (implicit DAG) | `stages:` (linear) + `needs:` (DAG) |
| Job dependencies | `needs: [job1, job2]` | `needs: [job1, job2]` |
| Conditional execution | `if: github.event_name == 'pull_request'` | `rules: - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'` |
| OIDC permission toggle | `permissions: id-token: write` | `id_tokens:` block per-job |
| OIDC role assume | `aws-actions/configure-aws-credentials@v4` | `aws sts assume-role-with-web-identity` (manual) |
| OIDC trust audience | `sts.amazonaws.com` (default of configure-aws-credentials) | `sts.amazonaws.com` (set via `id_tokens.<name>.aud`) |
| OIDC trust subject | `repo:<owner>/<repo>:ref:refs/heads/<branch>` | `project_path:<group>/<project>:ref_type:branch:ref:<branch>` |
| OIDC trust subject (PR) | `repo:<owner>/<repo>:pull_request` | (separate StringLike on branch glob) |
| Sandbox-per-change | `environment:` + separate `pull_request: closed` workflow | `environment:on_stop:` inline |
| Cleanup trigger | `on.pull_request.types: [closed]` workflow | `action: stop` on env named in deploy job |
| Auto-stop timer | (manual via scheduled cleanup) | `auto_stop_in: 4 hours` (built-in) |
| Concurrency control | `concurrency:` group + `cancel-in-progress` | `interruptible: true` + manual via API |
| Secrets | `secrets.AWS_OIDC_ROLE_ARN` | CI/CD variables UI (NOT for AWS keys; only for ARN) |
| Artifacts | `actions/upload-artifact@v4` | `artifacts:` block |
| CLI for PR/MR ops | `gh` (`gh pr diff`, `gh pr view`, `gh secret set`) | `glab` (`glab mr diff`, `glab mr view`, `glab variable set`) |

## The "what stays identical"

These pieces are IaC, not CI — they don't care which engine ran them:
- `infra/template-foundation.yaml` (foundation SAM stack)
- `infra/template-app.yaml` (app SAM stack)
- `infra/oidc-trust-policy.json` (trust policy template — only the issuer URL + sub format changes per engine; everything else identical)
- `src/pretraffic_hook/handler.py` (Lambda code)
- `tests/integration_test.py` (E2E test)
- `scripts/preflight-lambda-cap.sh` (pre-deploy guard)
- `.windsurfrules` v8 (Cascade contract)
- 4 scanners: bandit, semgrep, cfn-lint, cfn-nag (NOT tflint)

## The "what differs subtly"

### OIDC subject claim format

```
GitHub: repo:jaisingh-builds/accelya-agentic-aws:ref:refs/heads/module-11-jai
GitLab: project_path:accelya-trainer/accelya-agentic-aws:ref_type:branch:ref:module-11-jai
```

GitHub has a special `:pull_request` subject for PR events. GitLab uses
`:ref:` for both branches and merge requests but the `ref_type` distinguishes
(`branch` vs `merge_request_event` from `$CI_PIPELINE_SOURCE`).

### OIDC role assume mechanics

GitHub Actions ships `aws-actions/configure-aws-credentials@v4` which does
the JWT → assume-role dance in one step. GitLab CI requires a manual
`aws sts assume-role-with-web-identity` call followed by exporting the
three temp env vars (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_SESSION_TOKEN`). Both produce identical AWS-side behavior; only the
CI ergonomics differ.

### Sandbox cleanup

GitHub has no built-in `on_stop` for environments. We use a separate
workflow `.github/workflows/sandbox-cleanup.yml` that triggers on
`pull_request: closed`. GitLab's `environment:on_stop:` plus `action: stop`
on the named env gives you the same outcome in one file.

### Concurrency / cancellation

GitHub: `concurrency:` block at top of workflow cancels in-progress runs
on the same PR when a newer commit lands. GitLab: `interruptible: true`
per-job plus repo settings.

### Cascade MR/PR review

GitHub: `gh pr diff <pr-number> --patch > /tmp/pr.diff`
GitLab: `glab mr diff <mr-iid> --output diff > /tmp/mr.diff`

The Cascade prompt (`prompts/cascade-mr-review.txt`) is engine-agnostic
after the diff is captured; only the *grep checks for static AWS keys*
need engine-specific commands:

```
GitHub: gh secret list && gh variable list  → check for AWS_*
GitLab: glab variable list                  → check for AWS_*
```

## Pedagogically: why not just pick one?

Real airline shops use both. Knowing the mapping above means you can move
between engines without re-learning the agentic patterns. The patterns
(two-stack split, AutoPublishAlias, DeploymentPreference, 9-dim HITL,
Cascade MR-review) are constant across both.

## When the GitLab reference is the right read

- You're at a corp that's standardised on GitLab Premium
- You need merged-results pipelines (GitLab-only feature)
- You want native `environment:on_stop:` (cleaner than two-workflow GitHub pattern)
- You need protected-tag deploys with finer-grained perms than GitHub provides

Otherwise: GitHub is the runnable lab path for this programme.
