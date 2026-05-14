# Module 4 — Lab Guides (Standalone Reference)

> The Day 4 deck has these labs on slides 20-28; this file is your standalone reference.

---

## Day 4 prerequisites

```bash
cd accelya-agentic-aws
git checkout main && git pull --ff-only
git checkout -b module-4-<your-name>
mkdir -p design reviews prompts
```

Confirm Day 3 artefacts are present:
```bash
ls .windsurfrules                    # v1-draft from Day 3
ls prompts/v1_arch_options.txt        # Day 3 Lab 1
ls prompts/v2_validator.txt           # Day 3 Lab 3
```

---

## Lab 1 — Author the design doc with Cascade (45 min, pairs)

**Deliverable:** `design/m4-batch-pipeline-design.md` + `reviews/HITL_REVIEW-m4-design.md` (≥12/15). MR opened.

### Steps

```bash
# 1. Branch already created above. Verify:
git status   # On branch module-4-<your-name>

# 2. Pull the 7-layer prompt template
#    Reference: prompts/v7_design.txt is already in the starter repo
cat prompts/v7_design.txt | head -40
#    Read the 7 layers: ROLE, REPO RULES, CONSTRAINTS, EXAMPLES, TASK, OUTPUT FORMAT, REVIEW.

# 3. Fill the [TASK] section ONLY
#    Open prompts/v7_design.txt in Windsurf.
#    Find [LAYER 5] TASK — fill in with your specific design ask.
#    Leave the other 6 layers verbatim.

# 4. Cascade drafts the design doc
#    In Windsurf chat:
#      @cascade Read prompts/v7_design.txt. Author design/m4-batch-pipeline-design.md
#               per the OUTPUT FORMAT in layer 6.
#    Cascade produces design/m4-batch-pipeline-design.md (~600-1200 words).

# 5. Pair-HITL review on 5 dimensions
#    Open design/m4-batch-pipeline-design.md side-by-side with your pair partner.
#    Score each dimension 0-3 (anchors per Day 3 Concept 6).
#    Write reviews/HITL_REVIEW-m4-design.md with the 5 scores + evidence per dim.
#    Reference: design/m4-batch-pipeline-design.example.md shows ~15/15 standard.

# 6. Commit + open MR
git add design/ reviews/ prompts/
git commit -m "module-4: design doc + HITL review (Lab 1)"
git push -u origin module-4-<your-name>
# Open MR on GitHub:
#   https://github.com/jaisingh-builds/accelya-agentic-aws/compare/main...module-4-<your-name>
```

### Common gotchas

- **Cascade draft is 3000+ words** — first drafts are always too long. Reply: *"Tighten to 800 words; each section ≤150."*
- **Cascade misses a failure mode** — your `[TASK]` was vague. Add to TASK: "Cover ALL 6 failure modes including source-outage (Mode 6)."
- **Cascade uses generic vocabulary (`order_id`)** — the EXAMPLES layer in v7_design.txt prevents this; check it's not modified.
- **Pair disagrees on score** — take the LOWER score; document in MR.

---

## Lab 2 — Failure-mode walkthrough (45 min, SOLO)

**Deliverable:** `design/m4-failure-modes.md` with 6 sections (5 file-based traces + 1 source-outage design). MR shows 2 commits.

### Steps

```bash
# 1. The synthetic broken files are already in the repo at data/m4-failures/
#    (no S3 round-trip required — the files live in git for reproducibility).
ls data/m4-failures/

# Expected:
#   01-schema-drift.json
#   02-partial.json
#   03-duplicate.json
#   04-late-event.json
#   05-malformed.json
#   README.md
# (06 source-outage is DESIGN-ONLY — no file)

# 2. Inspect each file
#    Open them in Windsurf, or use CLI quickies:

# 01 — valid JSON; row 47 has wrong field; row 89 has string instead of number
python3 -c "import json; r=json.load(open('data/m4-failures/01-schema-drift.json')); print('row 47 keys:', list(r[47].keys())); print('row 89 fare_amount type:', type(r[89]['fare_amount']).__name__)"

# 02 — won't parse (intentionally truncated)
python3 -c "import json; json.load(open('data/m4-failures/02-partial.json'))" 2>&1 | head -3

# 03 — byte-identical to 01 (file_sha256 duplicate)
diff data/m4-failures/01-schema-drift.json data/m4-failures/03-duplicate.json && echo "FILES IDENTICAL"

# 04 — issue_date 95 days ago
python3 -c "import json; print(json.load(open('data/m4-failures/04-late-event.json'))[0]['issue_date'])"

# 05 — multiple parse errors
python3 -c "import json; json.load(open('data/m4-failures/05-malformed.json'))" 2>&1 | head -3

# 3. Categorise + trace one file end-to-end
#    For each file, identify:
#      - Category (schema_drift | partial | duplicate | late_event | malformed)
#      - Catch point (which function in src/validator/handler.py)
#      - Quarantine path (or non-quarantine handling)
#      - Sidecar JSON shape
#      - Log line shape
#    Reference: design/m4-failure-modes.example.md shows the trace pattern.

# 4. Repeat for the other 4 files
#    Critical: 03 (duplicate) and 04 (late event) are NOT quarantine.
#      03 → DynamoDB no-op (silent skip)
#      04 → validated/ with is_late=true flag

# 5. Add 6th section: source-outage (DESIGN-ONLY)
#    No file. Documents:
#      - Expected arrival cadence (every Tuesday 02:00 UTC for BSP)
#      - EventBridge scheduled checker design
#      - SNS topic for on-call paging
#      - Operator action playbook

# 6. Commit + extend the MR
git add design/m4-failure-modes.md
git commit -m "module-4: failure-mode catalogue (Lab 2)"
git push
```

### Common gotchas

- **Put 03 or 04 in quarantine** — re-read Concept 4. Duplicates = DDB no-op. Late events = `validated/` with flag.
- **Source-outage section uses same structure as file-based** — wrong. It has a different structure: no catch point in a Lambda; the catch is an EventBridge schedule.
- **Files accidentally modified** — `data/m4-failures/` is read-only by convention. If you broke a file: `python3 scripts/generate_m4_failures.py` regenerates them.

### Regenerating the files

If `data/m4-failures/` ever needs to be regenerated (you modified a file by accident, or you want a fresh `04-late-event.json` with today's "95 days ago" date):

```bash
python3 scripts/generate_m4_failures.py
# Writes all 5 files. Idempotent — files 01/02/03/05 reproduce identically; 04 shifts with today's date.
```

---

## Lab 3 — Promote `.windsurfrules` v1-draft → v1-final (45 min, pairs)

**Deliverable:** `.windsurfrules` at repo root (v1-final state) + `reviews/m4-windsurfrules-test.md` (2 test passes). MR shows 3 commits.

### Steps

```bash
# 1. Pull the v1-final template
#    Reference: docs/.windsurfrules-v1-final.template
cat docs/.windsurfrules-v1-final.template | head -60

# 2. Customise CONSTRAINTS with live sandbox caps
#    Open .windsurfrules in Windsurf.
#    Replace the CONSTRAINTS section with the template's CONSTRAINTS section.
#    Verify all sandbox caps match:
#      Bedrock 50 inv / 20K tok
#      Lambda 10 functions / 2048 MB / python3.12
#      SageMaker 1 endpoint / no GPU
#      Glue 3 jobs / 4 DPU / 6 DPU-h
#      No Bedrock Agents/AgentCore/Studio/KB

# 3. Add EXAMPLES referencing real artefacts
#    Add references to:
#      - src/validator/handler.py (Day 2)
#      - design/m4-batch-pipeline-design.md (Day 4 Lab 1)
#      - design/m4-failure-modes.md (Day 4 Lab 2)
#      - Programme schema fields (pnr, airline_code, fare_class, od_pair, ...)
#      - Idempotency table (4 guards in one table)

# 4. TEST in a FRESH chat (critical — old chats use stale context)
#    In Windsurf:
#      File → Close ALL Cascade chats
#      Open a NEW chat
#      Prompt: "Scaffold a hello-world Lambda for the cancellation envelope."
#    Cascade output MUST include:
#      - File at src/cancellation_hello/handler.py (REPO RULES)
#      - References to cancellation envelope fields (EXAMPLES)
#      - NO mention of Bedrock Agents (CONSTRAINTS)
#      - Region ap-south-1 (CONSTRAINTS)
#    Capture transcript:
nano reviews/m4-windsurfrules-test.md
# Title: "M4 .windsurfrules v1-final test — pass 1"
# Body: paste Cascade transcript + per-criterion pass/fail

# 5. Revise + retest (if any criterion failed)
#    Identify which CONSTRAINT or EXAMPLE wasn't tight enough.
#    Update .windsurfrules.
#    Open ANOTHER new chat. Re-prompt the same hello-world ask.
#    Diff the responses. Stop when ALL criteria pass.
#    Append "pass 2" section to reviews/m4-windsurfrules-test.md.

# 6. Commit + close out the MR
git add .windsurfrules reviews/m4-windsurfrules-test.md
git commit -m "module-4: .windsurfrules v1-final + test (Lab 3)"
git push

# Update MR description on GitHub:
#   "M4 Lab 1 — design doc"
#   "M4 Lab 2 — failure-mode catalogue"
#   "M4 Lab 3 — .windsurfrules v1-final"
# Tag your pair partner as reviewer.
```

### Common gotchas

- **Test in an OPEN chat** — the test is meaningless. Cascade already loaded older `.windsurfrules`. Open a NEW chat after saving the file.
- **Cascade still proposes Bedrock Agents** — your CONSTRAINTS aren't prominent enough. Move to top of CONSTRAINTS section; add forbidden services as a bullet list.
- **EXAMPLES too vague** — "use airline vocabulary" doesn't help. Specific examples: cancellation envelope shape, settlement record shape, IAM excerpt shape.
- **Only one test pass captured** — slide 27 requires TWO passes (one before revisions, one after). Without two, the discipline of iteration isn't documented.

---

## End-of-module cleanup

```bash
bash scripts/cleanup_module4.sh
```

That script (1) verifies no AWS resources were accidentally provisioned, (2) checks Bedrock budget (should be 0 today), (3) commits any pending artefacts, (4) pushes the branch.

**Do NOT delete the Day 2 Lambda** — it stays for D5+.

---

## Day 4 in numbers

| Metric | Value |
|---|---|
| New Lambdas deployed | 0 (design only) |
| Lambda count cumulative | 1 of 10 (D2 starter validator) |
| AWS Bedrock Runtime invocations | 0 today; cumulative ~2-5 of 50 |
| New artefacts | 4: design doc + failure-mode catalogue + .windsurfrules v1-final + 2 reviews |
| PR commits | 3 (Lab 1 + Lab 2 + Lab 3) |
| .windsurfrules version | v1-final (4 sections); v2 (adds BATCH CONTEXT) ships Day 5 |

---

## What's coming on Day 5

Module 5 — Agentic Batch Processing Implementation. **The design from Day 4 becomes 4 Lambdas tomorrow** — chunker, validator, lander, dlq_replayer. `.windsurfrules` promotes to v2 with two batch blocks: ASL CHUNK CONTEXT (for the main pipeline) + SQS PARTIAL-BATCH CONTEXT (for the standalone partial-batch demo).

Bring today's branch + design doc — Day 5's Cascade prompts reference `design/m4-batch-pipeline-design.md` as project context.

---

*See `Day4_Module4_Batch_Pipeline_Design.pptx` slides 20-28 for the deck's full visual treatment.*
