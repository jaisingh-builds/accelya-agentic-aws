# Module 1 — Lab Guides (Standalone Reference)

> The Day 1 deck has these labs on slides 23–31; this file is your standalone reference if you're working ahead, catching up, or stuck offline.

---

## Lab 1 — Environment Verification (30 min)

**Deliverable:** `scripts/verify_bedrock.py` exits 0 and prints two architecture options as JSON.

### Steps

```bash
# 1. Clone & open
git clone https://github.com/jaisingh-builds/accelya-agentic-aws.git
cd accelya-agentic-aws
windsurf .
# Expected: Cascade panel opens, repo tree visible, .windsurfrules picked up.

# 2. Test Cascade with a non-AWS prompt (in Cascade chat):
@cascade "Read README.md and tell me the lab structure."
# Expected: structured summary; token cost displayed.

# 3. Verify AWS access in Mumbai
aws sts get-caller-identity --region ap-south-1
aws bedrock list-inference-profiles --region ap-south-1 \
  --query 'inferenceProfileSummaries[?contains(inferenceProfileId, `claude`)].inferenceProfileId'
# Expected: your IAM ARN + the APAC Claude profile in the list.

# 4. Run the verify script
python3 scripts/verify_bedrock.py
# Expected: ✅ Bedrock Converse OK + token counts + JSON architecture options.
```

### Checkpoint (slide 25)

- ✓ `verify_bedrock.py` exits 0 and prints parseable JSON.
- ✓ Cascade can edit a file in your repo.
- ✓ GitHub PR creation works from your branch.
- ✓ AWS calls succeed in ap-south-1.
- ✓ `response["usage"]` shows `inputTokens > 0` and `outputTokens > 0`.

### Top 5 gotchas

1. **Wrong region** — `export AWS_DEFAULT_REGION=ap-south-1`
2. **No Bedrock model access** — `AccessDeniedException`; ask trainer to escalate to client
3. **Old boto3** — `python3 -m pip install -U boto3`
4. **Wrong model identifier** — use `apac.anthropic.claude-3-5-sonnet-20241022-v2:0` exactly
5. **GitHub SSH/HTTPS missing** — set up `gh auth login` or add an SSH key

---

## Lab 2 — Business Requirement → Prompt (45 min, pairs)

**Deliverable:** `prompts/m1-arch-v1.md` — a 5-section prompt that turns the BR in `briefs/m1.md` into a structured Bedrock task.

### The BR

> "We receive a daily ticket-issue file from each airline; we need to validate it, store it for analytics, and flag bad records for ops."

### Steps

1. Read `briefs/m1.md` end-to-end.
2. Read `docs/prompt-template.md` for the 5-section anatomy.
3. Read `glossary/airline.md` for the field vocabulary.
4. In Cascade, ask:
   ```
   @cascade Read /docs/prompt-template.md and scaffold a 5-section prompt
   for the BR in /briefs/m1.md. Use airline vocabulary from /glossary/airline.md.
   ```
5. Refine the scaffolded prompt by hand — add specifics about file size, fields, region, sandbox caps, non-goals.
6. Commit to `prompts/m1-arch-v1.md`. See `prompts/m1-arch-v1.example.md` for a reference shape.

### Checklist

- ✓ All 5 sections present (Role / Context / Task / Non-goals / Output format)
- ✓ Airline vocabulary used (`pnr`, `od_pair`, `fare_class` — NOT `order_id`)
- ✓ Sandbox caps referenced in Context
- ✓ Non-goals lists specific services Cascade tends to over-propose
- ✓ Output format specifies JSON schema with field names

---

## Lab 3 — Generate, Score, Choose (60 min, table groups of 3-4)

**Deliverable:** scorecard CSV + decision PR with rationale.

### Steps

1. **Run prompt** — Use your Lab 2 `prompts/m1-arch-v1.md` against Bedrock (or run via Cascade). Save the raw response to `outputs/m1-arch-options.json`.
2. **Capture options** — `cat outputs/m1-arch-options.json | python3 -m json.tool` to verify it's parseable JSON.
3. **Score with HITL** — Each table member independently scores both options on 5 dims (0-3 each). Save scores as `reviews/m1-scorecard.csv` with columns: `reviewer,option,correctness,security,observability,scalability,cost,total,verdict`.
4. **Decide & commit** — Discuss, vote, write rationale. Open a PR titled `Module 1 decision: architecture for ticket-issue pipeline`.

### Scoring anchors (programme-wide)

| Dim | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **Correctness** | doesn't compile / hallucinated | wrong field / API name | matches spec; happy path | spec + edge cases tested |
| **Security** | `Action:*` / hardcoded secrets | some wildcards | no wildcards; secrets env | ARN-scoped + Conditions; PII tagged |
| **Observability** | `print` / silent except: pass | JSON logs only | logs + classified errors | powertools Logger + correlation_id + EMF |
| **Scalability** | unbounded / non-idempotent | idempotent only | idempotent + bounded | + 10× tested |
| **Cost** | wrong service for workload | right service; cost ignored | right service; no sampling | + sampled + measurable |

**Pass:** ≥12/15 AND every dim ≥2.

### Sample scorecard verdict

```
Option A (S3 → Lambda → Athena):  3+3+2+2+3 = 13/15 — PASS (all dims ≥ 2)
Option B (S3 → Glue → Catalog):    3+3+3+3+1 = 13/15 — REVISE (Cost = 1 < 2)
```

Same total, different verdict. **The minimum dim is what decides PASS/REVISE, not the total.**

### Decision PR rationale must include

- Which option chose (1 line)
- Why this option's weaknesses are acceptable (2-3 bullets)
- What we'd revisit and when (2-3 bullets)
- Links to evidence (`outputs/m1-arch-options.json`, `reviews/m1-scorecard.csv`)

See `prompts/m1-arch-v1.example.md` and slide 31 of the Day 1 deck for the worked example.

---

## End-of-module cleanup

```bash
bash scripts/cleanup_module1.sh
```

That script (1) empties your S3 learner-sandbox prefix, (2) checks Bedrock invocation counts, (3) commits prompts/outputs/reviews, (4) pushes the branch, (5) verifies.

Open the PR after cleanup completes. The PR is the artefact reviewers see — make sure it has:
- A clear title (`Module 1 decision: ...`)
- The decision rationale in the description
- Links to the scorecard and outputs files
- HITL_REVIEW.md filled at module level

---

*See `Day1_Module1_Foundation.pptx` for the deck's full visual treatment of these labs.*
