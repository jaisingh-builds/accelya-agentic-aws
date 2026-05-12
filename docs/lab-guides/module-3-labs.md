# Module 3 — Lab Guides (Standalone Reference)

> The Day 3 deck has these labs on slides 20-28; this file is your standalone reference.

---

## Day 3 prerequisites

```bash
cd accelya-agentic-aws
git checkout main && git pull --ff-only
git checkout -b module-3-<your-name>

# Verify your AWS access still works (same as Day 2)
aws sts get-caller-identity --region ap-south-1
```

If `sts get-caller-identity` fails, fix before lab time.

---

## Lab 1 — Audit folders + .windsurfrules + 5-section prompt (45 min, pairs)

**Deliverable:** branch `module-3-<your-name>` with audit folders + `.windsurfrules` v1 + `prompts/v1_arch_options.txt` + `reviews/m3-cascade-rules-test.md` + open MR.

### Steps

```bash
# 1. Branch + scaffold audit folders
export LEARNER=<your-name>
mkdir -p prompts reviews design
for d in prompts reviews design; do touch $d/.gitkeep; done
git add prompts/ reviews/ design/

# 2. Author .windsurfrules v1 — see Day 3 slide 16 for the template
#    Copy from prompts/library/architecture-generation.md or the deck.
#    Required sections: REPO RULES, CONSTRAINTS, EXAMPLES, REVIEW.
nano .windsurfrules

# 3. Author the 5-section prompt for Lab 2
#    Reference: prompts/v1_arch_options.example.txt in the starter repo
nano prompts/v1_arch_options.txt

# 4. Test Cascade picks up .windsurfrules
#    Open a NEW Windsurf chat (fresh session — old chats use stale context):
#      @cascade Scaffold a hello-world Lambda for the cancellation envelope.
#
#    Expected Cascade output:
#      - Place file at src/cancellation_hello/handler.py (REPO RULES section)
#      - Use event_id, event_type, airline_code, pnr (EXAMPLES section)
#      - NOT propose Bedrock Studio / Knowledge Bases (CONSTRAINTS section)
#
#    Capture the transcript:
nano reviews/m3-cascade-rules-test.md
#    Title: "M3 .windsurfrules pickup test"
#    Body: paste Cascade's transcript + a 1-line verdict (pass/fail per criterion)

# 5. Pair-review the prompt + .windsurfrules
#    Pair partner reads .windsurfrules + v1_arch_options.txt + test transcript.
#    One improvement suggested (e.g. tighten TASK; add missing constraint).
#    Accept (commit) or reject (note in MR).

# 6. Commit + push
git add .windsurfrules prompts/v1_arch_options.txt reviews/m3-cascade-rules-test.md
git commit -m "module-3: audit folders + .windsurfrules v1 + v1_arch_options.txt"
git push -u origin module-3-<your-name>
```

### Common gotchas

- **`.windsurfrules` not picked up** — file at repo root (NOT in `docs/`), file committed, new chat opened.
- **Cascade uses `order_id`** instead of `pnr` — your EXAMPLES section is too short. Paste the full cancellation envelope from `prompts/library/architecture-generation.md`.
- **Cascade proposes Glue Streaming** despite REVIEW NOTES banning it — your REVIEW NOTES are buried. Move them to the top of the prompt or repeat in TASK.

---

## Lab 2 — Bedrock multi-architecture + scorecard (45 min, pairs)

**Deliverable:** `scripts/generate_architectures.py` + `outputs/m3-arch-options.json` + `reviews/m3-arch-scorecard.csv` + `reviews/m3-arch-decision-MR.md`. MR shows 2 commits.

### Steps

```bash
# 1. Cascade-author the Converse script (in Windsurf chat):
#    @cascade Create scripts/generate_architectures.py per Concept 4 of Day 3 deck.
#             It should: read prompts/v1_arch_options.txt; call Bedrock Converse;
#             temperature=0.2, maxTokens=2000; parse JSON with strip_fences() helper;
#             assert 2-3 options; FLAG sandbox_compatible=False (don't crash);
#             write outputs/m3-arch-options.json.
#    Cascade output: ~35-45 lines.
#
#    Reference: scripts/generate_architectures.py in the starter repo
mkdir -p scripts outputs
# Review the Cascade output against the reference before running.

# 2. Run + capture JSON
export BEDROCK_MODEL_ID=apac.anthropic.claude-3-5-sonnet-20241022-v2:0
python3 scripts/generate_architectures.py
# Expected: summary with 2-3 option names + sandbox-compatible flags.

# Sanity check the JSON shape
python3 <<'PY'
import json
d = json.load(open('outputs/m3-arch-options.json'))
print(f'options: {len(d)}')
for o in d:
    flag = '' if o.get('sandbox_compatible') else '  [DISQUALIFIED]'
    print(f"  - {o['name']} (sandbox: {o.get('sandbox_compatible')}){flag}")
PY

# 3. Pair-score on the 5-dim scorecard
#    Each option scored 0-3 on Correctness, Security, Observability, Scalability, Cost.
#    Pair disagreements: take the LOWER score.
#    Reference: reviews/m3-arch-scorecard.template.csv
cp reviews/m3-arch-scorecard.template.csv reviews/m3-arch-scorecard.csv
# Edit reviews/m3-arch-scorecard.csv — replace placeholders with your scores.

# 4. Pick winner + decision MR
#    Reference shape:
nano reviews/m3-arch-decision-MR.md
# (See Day 3 deck slide 24 step 4 for the markdown template.)

# 5. Verify Bedrock budget
PROFILE=apac.anthropic.claude-3-5-sonnet-20241022-v2:0
START=$(python3 -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).isoformat().replace("+00:00","Z"))')
END=$(python3 -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).isoformat().replace("+00:00","Z"))')

for METRIC in Invocations InputTokenCount OutputTokenCount; do
  aws cloudwatch get-metric-statistics --namespace AWS/Bedrock \
    --metric-name $METRIC --dimensions Name=ModelId,Value=$PROFILE \
    --start-time $START --end-time $END --period 3600 --statistics Sum \
    --region ap-south-1
done
# Expected: Invocations = 1 required + up to 3-4 if you regenerated.

# 6. Commit + push
git add scripts/ outputs/ reviews/m3-arch-scorecard.csv reviews/m3-arch-decision-MR.md
git commit -m "module-3: Bedrock arch options + scorecard + decision MR (Lab 2)"
git push
```

### Common gotchas

- **JSON parse fails** — Bedrock wrapped output in ```` ```json ```` fences. Make sure `strip_fences()` helper is in the script.
- **Bedrock returns 1 or 4 options** — prompt loosely worded. Either loosen the assertion or tighten the prompt.
- **All options score below 10/15** — prompt was vague. Revise prompt + re-run; Bedrock will produce better options.
- **Pair disagrees on scores** — take the LOWER score; document disagreement in the decision MR.

---

## Lab 3 — Weak vs Strong validator (45 min, SOLO)

**Deliverable:** `src/weak_validator/handler.py` (trainer-provided) + `reviews/HITL_REVIEW-weak_validator.md` (~5/15) + `prompts/v2_validator.txt` + `src/strong_validator/handler.py` (Cascade-generated against v2) + `reviews/HITL_REVIEW-strong_validator.md` (~14/15) + `reviews/m3-prompt-refinement-diff.md`. MR shows 3 commits.

### Steps

```bash
# 1. The trainer-provided weak validator should already be in your repo from Day 1 prep:
ls src/weak_validator/handler.py
# If missing: `git pull origin main` (the trainer pushed it before Day 1).

# 2. Run 5-dim HITL review on the weak version — expect ~5/15
#    Reference: src/weak_validator/handler.py was deliberately built with all 6 Concept-5 failure modes.
#    Identify which failure mode triggered which dim drop.
nano reviews/HITL_REVIEW-weak_validator.md
# (See Day 3 deck slide 27 step 2 for the markdown template.)
# Expected score: ~5/15, FAIL.

# 3. Author prompts/v2_validator.txt — close all 6 failure modes
#    Each REVIEW NOTES bullet should be specific:
#      - "use field name pnr EXACTLY (NOT order_id)"  -- closes Mode 2
#      - "NEVER except Exception: pass"               -- closes Mode 5
#      - etc.
nano prompts/v2_validator.txt

# 4. Cascade-author strong validator against v2 prompt (in Windsurf):
#    @cascade Read prompts/v2_validator.txt + .windsurfrules + EXAMPLES.
#             Author src/strong_validator/handler.py.
#             Include a docstring listing which Concept-5 failure mode each design choice closes.

# 5. Re-run 5-dim HITL review on strong — expect ~14/15
nano reviews/HITL_REVIEW-strong_validator.md
# Expected: 13-15/15, PASS (every dim >=2).

# 6. Write the prompt-refinement diff
nano reviews/m3-prompt-refinement-diff.md
# (See Day 3 deck slide 27 step 6 for the markdown template — table mapping v2 changes to dim lifts.)

# 7. Commit + push
git add src/ prompts/v2_validator.txt reviews/HITL_REVIEW-*.md reviews/m3-prompt-refinement-diff.md
git commit -m "module-3: weak vs strong validator; prompt refinement (Lab 3)"
git push
```

### Common gotchas

- **Skipping the weak review** — defeats the +9-point lift demonstration. Do the weak review first.
- **Generic REVIEW NOTES in v2** — "be careful with security" doesn't constrain Cascade. Specific bans + requirements (with field names) do.
- **Strong validator scored <12** — your v2 REVIEW NOTES weren't specific enough, OR `.windsurfrules` isn't being read. Re-test from Lab 1 step 4.
- **Strong validator looks similar to weak** — Cascade didn't fully read v2 prompt. Open a new chat; explicitly point at v2 prompt in your ask.

---

## End-of-module cleanup

```bash
bash scripts/cleanup_module3.sh
```

That script (1) verifies no AWS resources were accidentally provisioned, (2) checks Bedrock budget, (3) commits any uncommitted artefacts, (4) pushes the branch.

**Do NOT delete the Day 2 Lambda** — it stays for D4+.

---

## Day 3 in numbers

| Metric | Value |
|---|---|
| New Lambdas deployed | 0 (foundation day) |
| Lambda count cumulative | 1 of 10 (D2 starter validator) |
| AWS Bedrock Runtime invocations | ~1-4 today; cumulative ~2-5 of 50 |
| New artefacts in branch | 9 (audit folders + .windsurfrules + 2 prompts + 2 src files + 2 HITL reviews + scorecard + decision MR + diff) |
| PR commits | 3 (Lab 1 + Lab 2 + Lab 3) |

---

## What's coming on Day 4

Module 4 — Batch Pipeline Design on AWS. Design before code. You'll write `/design/m4-batch-pipeline-design.md` based on today's prompt + .windsurfrules. Idempotency table schema. Failure-mode catalogue. `.windsurfrules` v2 adds BATCH CONTEXT (Records[], partial-batch protocol, idempotency contract).

Bring today's branch — D4 reads from your `.windsurfrules` + prompts/ as the foundation for the batch design.

---

*See `Day3_Module3_Agentic_AI_Foundations.pptx` slides 20-28 for the deck's full visual treatment.*
