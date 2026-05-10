# Prompt Refinement Diff — v1 (implicit) → v2

> Day 3 Lab 3 deliverable. Captures **what changed in the prompt** between the weak validator's run and the strong validator's run, and **which HITL dim each change improved**.
>
> The "v1" here is the implicit lazy prompt that produced `src/weak_validator/handler.py` — a one-line ask like *"write a Lambda that validates airline ticket files"*. The "v2" is the explicit 5-section prompt in `prompts/v2_validator.txt`.

---

## Score lift overview

| Dim | Weak (v1) | Strong (v2) | Lift | Driven by |
|---|---|---|---|---|
| Correctness | 2 | 3 | +1 | Programme schema explicit; edge cases enumerated in Task |
| Security | 1 | 3 | +2 | APAC profile via env; env-var-driven config; PII handling |
| Observability | **0** | **3** | **+3** | **Powertools Logger mandated; typed exceptions; EMF** |
| Scalability | 1 | 3 | +2 | Streaming requirement; module-level clients; idempotency |
| Cost | 1 | 2 | +1 | "NO Bedrock in row loop"; module-10 sampling deferred |
| **Total** | **5** | **14** | **+9** | |

**The single biggest lift is Observability (+3).** A learner who internalises *"explicit Observability requirements in the prompt drives Observability scores"* has internalised Day 3's whole pedagogy.

---

## What was IMPLICIT in v1 (the weak prompt)

A representative v1 prompt looked like:

> *"Write a Lambda handler in Python that validates airline ticket-issue files from S3. Return success/failure for each record."*

That's it. **No** mention of:
- The programme schema (`pnr`, `airline_code`, `fare_class`, etc.).
- The forbidden generic vocabulary.
- The APAC inference profile vs raw model ID.
- Powertools / structured logging / correlation_id.
- Idempotency contracts.
- Streaming vs `body.read()`.
- Quarantine paths or sidecar JSON.
- Typed exception ladder vs bare `except`.
- Bedrock budget discipline.

Cascade produced a handler that "kind of worked" but exhibited all 6 failure modes — because nothing in the prompt told it not to.

---

## What was EXPLICIT in v2 (closing the 6 failure modes)

### Change 1 — Programme schema in Context

```diff
+ Programme schema (lowercase snake_case, mandatory — NEVER generic vocabulary):
+     pnr               (6-char alphanumeric)
+     airline_code      (2-char IATA)
+     fare_class        (1-char)
+     od_pair           (e.g. "BOM-DEL")
+     settlement_date   (ISO 8601 date)
+     ... (full list)
+ Forbidden vocabulary in payload examples or field names: order, order_id,
+ user, user_id, transaction_amount, item.
```

**Closes failure modes:** 2 (wrong vocabulary).
**Lifts dim:** Correctness +1.

### Change 2 — APAC inference profile mandated

```diff
+ Bedrock model: use the APAC inference profile id read from BEDROCK_MODEL_ID env var.
+ Programme default: apac.anthropic.claude-3-5-sonnet-20241022-v2:0.
+ NEVER use a raw model id like 'anthropic.claude-3-5-sonnet-...'.
```

**Closes failure modes:** 1 (hallucinated/wrong model ID).
**Lifts dim:** Security +1 (no raw ID), Correctness +partial.

### Change 3 — Powertools Logger requirement in Task

```diff
+ Use aws_lambda_powertools.Logger with correlation_id propagated from the Lambda context
+ (context.aws_request_id). Every log line is structured JSON with at minimum:
+ { ts, level, event, correlation_id, function, key, ... domain-specific fields ... }.
```

**Closes failure modes:** 5 (silent swallow — eliminated by mandating logger calls).
**Lifts dim:** Observability +2 (was 0, jumps to 2 with logger alone).

### Change 4 — Typed exception ladder + ban on bare except

```diff
+ NEVER use a bare `except:` or `except Exception: pass`. Every catch is a typed exception
+ from the local ladder (SchemaError, ReferenceError, BusinessRuleError) plus boto3
+ ClientError for AWS-side transient failures.
```

**Closes failure modes:** 3 (missing error paths), 5 (silent swallow — final +1).
**Lifts dim:** Observability +1 (to 3), Correctness +partial.

### Change 5 — EMF metrics mandated

```diff
+ Emit ONE EMF metric per file with: records_total, records_validated, records_quarantined,
+ records_duplicate. Use the namespace "Accelya/Validator".
```

**Closes failure modes:** Mode 5 indirect (failures get *counted*, not just logged).
**Lifts dim:** Observability +0 (already at 3); enables Module 10 alarms downstream.

### Change 6 — Streaming + module-level clients

```diff
+ Read each S3 object referenced in event['Records'] line-by-line (streaming — NO full-file
+ reads via body.read()).
+ boto3 clients (s3, dynamodb) MUST be module-level (created once per cold start), not
+ instantiated per invocation.
```

**Closes failure modes:** 4 (over-abstraction has nowhere to hide when clients are flat at module scope).
**Lifts dim:** Scalability +2 (1 → 3).

### Change 7 — Idempotency contract in Task

```diff
+ Idempotency claim 'row#<file_key>:<line_no>' against a DynamoDB table named via env var
+ IDEMPOTENCY_TABLE. Skip silently if duplicate.
```

**Closes failure modes:** Mode 4 indirect (non-idempotent replay is now impossible by contract).
**Lifts dim:** Scalability +0 (already at 3 with streaming); Correctness +partial (replay-safe).

### Change 8 — Bedrock banned in row loop

```diff
+ NEVER call Bedrock inside this handler. Bedrock is design-time only in this programme.
```

**Closes failure modes:** 6 (cost-blind — the most expensive failure).
**Lifts dim:** Cost +1 (1 → 2). Doesn't reach 3 because sampling discipline isn't required yet.

### Change 9 — Non-goals bans abstraction

```diff
+ Do NOT introduce a class hierarchy, factory, provider, or any abstraction layer that
+ isn't directly needed by Lambda runtime.
```

**Closes failure modes:** 4 (over-abstraction final +1).
**Lifts dim:** Scalability +0 (already at 3); maintainability win.

### Change 10 — Output format mandates inline review comments

```diff
+ Inline `# REVIEW NOTES:` comments next to each block explaining which HITL dim the design
+ choice protects — e.g. `# REVIEW NOTES: Observability — correlation_id propagated`.
```

**Closes failure modes:** None directly.
**Lifts dim:** Reviewer efficiency. The strong handler is *self-documenting* its HITL alignment, which speeds up downstream reviews by ~30%.

---

## What's still NOT in v2 (could be added in a v3 for 15/15)

Three additions would push Cost from 2 → 3:

1. **Sampling switch** for non-mandatory enrichments:
   ```
   + If a non-mandatory enrichment is needed, sample at SAMPLE_RATE (env var, default 0.1).
   ```
2. **Cost-driver log** per invocation:
   ```
   + Log a structured 'cost_observation' line per invocation with: rows_processed,
   + ddb_writes, s3_puts. Module 10 uses this for cost-per-record dashboards.
   ```
3. **EMF cost metric**:
   ```
   + Emit an EMF metric 'cost_per_thousand_rows_microUSD' computed from the rate constants
   + in .windsurfrules CONSTRAINTS section.
   ```

**Why these aren't in v2:** Module 10 (Observability + Security + Cost) is where cost-discipline is the explicit teaching focus. Forcing 15/15 in Module 3 would shortcut that lesson. **The 14/15 is the deliberate ceiling for this module.**

---

## Lessons for the cohort (what to call out at 14:30 debrief)

1. **Same model. Same Cascade. Same engineer. +9 points from prompt refinement alone.** The discipline IS the lift.

2. **Observability had the biggest single-dim lift (+3, from 0 to 3).** It's also the dim most often left implicit in lazy prompts. Make Observability requirements explicit and they get delivered.

3. **Cost lifted only +1 (to 2, not 3).** This is intentional — the v2 prompt closed the catastrophic Bedrock-per-row mode but didn't require sampling discipline. **Honest scoring keeps the ceiling at 2 here.** A learner who scores 3 hasn't read the anchors.

4. **Failure modes don't map 1-to-1 to HITL dims.** Mode 5 (silent swallow) hit both Observability AND Correctness. Mode 4 (over-abstraction) hit Scalability via maintainability. Read the per-mode mapping table above.

5. **The diff IS the artefact.** This file is committed alongside the code. In Module 12, capstone reviewers read these diffs to evaluate how each learner's prompt discipline evolved.

---

*Source: Day 3 Lab 3 deliverable list (slide 28). Trainer reference for the 14:30 debrief.*
