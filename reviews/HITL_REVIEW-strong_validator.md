# HITL_REVIEW — src/strong_validator/handler.py

> **Reference scorecard** for the Day 3 Lab 3 v2-prompt output.
> Trainer reference. Learners score independently; the calibration discussion at 14:30 reconciles deltas.

---

**Artefact:** `src/strong_validator/handler.py`
**Produced by:** Cascade, against `prompts/v2_validator.txt`
**Reviewer:** Jai Singh (trainer reference)
**Date:** 2026-05-11
**Module:** M3
**Lab:** Lab 3 (weak-vs-strong critique)

---

## The score (0–3 per dim · PASS = ≥12/15 AND every dim ≥2)

| Dim            | Score | Evidence (one line per dim)                                                                            |
|----------------|-------|--------------------------------------------------------------------------------------------------------|
| Correctness    | **3** | Programme schema enforced; edge cases covered (malformed JSON, missing fields, future-dated, duplicate). |
| Security       | **3** | Env-var driven config; no hardcoded secrets; no `Action:*`; APAC profile referenced via env not raw ID. |
| Observability  | **3** | Powertools Logger + `correlation_id_path="awsRequestId"`; classified errors; EMF metrics emitted.       |
| Scalability    | **3** | Line-by-line streaming via `iter_lines`; module-level clients; idempotency `row#<key>:<line>` claims.   |
| Cost           | **2** | Workload-appropriate (Lambda); no Bedrock invocations in row loop. But no sampling discipline yet.     |
| **TOTAL**      | **14/15** | **PASS** — well clear of 12/15 bar AND every dim ≥ 2.                                              |

**Verdict:** PASS
**Min dim:** Cost = 2 (above the per-dim ≥ 2 rule)

**Δ vs weak validator:** 5/15 → 14/15. A +9 lift driven by closing all 6 Concept-5 failure modes via the v2 prompt.

---

## Per-dimension detail

### Correctness — `3/3`

**Why 3 (not 2):**
- Programme schema `REQUIRED_FIELDS = {pnr, airline_code, fare_class, od_pair, settlement_date, ticket_number, issue_date, fare_amount, currency, agency_iata, source_system}` enforced explicitly.
- Edge cases handled:
  - Empty/blank lines skipped (continue, don't crash).
  - Malformed JSON → `quarantine/malformed/` with sidecar.
  - Missing required fields → `SchemaError` → `quarantine/schema_drift/`.
  - Invalid airline_code → `ReferenceError` → `quarantine/reference_drift/`.
  - Future-dated `settlement_date` → `BusinessRuleError` → `quarantine/business_rule/`.
  - Duplicate (idempotency replay) → silently skip with structured log.
- Real boto3 APIs only — no hallucinated method names.
- No generic vocabulary — `pnr`/`od_pair`/`fare_amount` throughout.

**Closes failure modes:** 1 (hallucinated APIs), 2 (wrong vocabulary), 3 (missing error paths).

---

### Security — `3/3`

**Why 3:**
- Env-var driven: `BUCKET`, `IDEMPOTENCY_TABLE`, `LEARNER` — no hardcoded values.
- Bedrock model ID via env (`BEDROCK_MODEL_ID`); APAC inference profile is the default, not a raw ID.
- No `Action:*` or `Resource:*` anywhere (the code itself; SAM template separately enforces this).
- No PII written to logs — `original_record` is logged in the sidecar JSON only when quarantining, never in info-level logs.
- All typed exceptions; no information leakage via bare `except` printing internals.

**Potential drop to 2:** If the IAM policy attached to this Lambda's role is later found to use `s3:*`, the score drops. The handler itself is clean; the deployment-side IAM is reviewed separately.

---

### Observability — `3/3`

**Why 3 (the highest-lift dim from weak → strong):**
- `aws_lambda_powertools.Logger` at module scope.
- `@logger.inject_lambda_context(correlation_id_path="awsRequestId")` decorator wires `correlation_id` automatically.
- Every log line is structured JSON via Powertools (level, ts, service, function, correlation_id, ...).
- Errors classified into 4 typed categories (`SchemaError`, `ReferenceError`, `BusinessRuleError`, `ClientError`).
- EMF metrics emitted: `records_total`, `records_validated`, `records_quarantined`, `records_duplicate` in `Accelya/Validator` namespace.
- Quarantine sidecar JSON captures `correlation_id` + `trace_id` for cross-service lookup.
- **No** `print()`, **no** bare `except`, **no** silent swallow.

**Closes failure modes:** 5 (silent swallow — was the weak validator's catastrophic Observability=0).

---

### Scalability — `3/3`

**Why 3:**
- Line-by-line streaming via `obj["Body"].iter_lines()` — no `body.read()` of the full file. 50 MB or 500 MB, memory footprint is constant.
- Module-level boto3 clients (`s3 = boto3.client("s3")` at module scope) — created once per cold start, reused across invocations.
- Idempotent: `row#<file_key>:<line_no>` claim against DynamoDB before persisting. Replay is safe; duplicates skip silently.
- TTL on idempotency claims (30 days) — table doesn't grow unbounded.
- Flat handler: one `lambda_handler` plus 5 pure helpers. No factory pattern, no class hierarchy. Maintainable.

**Closes failure modes:** 4 (over-abstraction), partial mitigation of unbounded memory.

---

### Cost — `2/3`

**Why 2 (not 3):**
- ✅ Right service for the workload — Lambda for 50 MB batch validation is correct.
- ✅ NO Bedrock calls inside the row loop — the v2 prompt explicitly bans them, closing failure mode 6.
- ✅ DynamoDB on-demand billing (no provisioned capacity for sporadic load).
- ❌ **No sampling discipline** — every row gets full schema + reference + business-rule validation. For a 10K-row file that's 10K DynamoDB writes for the idempotency claim. Acceptable at lab scale; production would sample at 10% beyond a threshold.
- ❌ **No `cost_drivers` documentation** in code comments. The strong handler doesn't say "each row costs ~X μUSD" anywhere.

**Why not 1:** The wrong-service errors (Bedrock-per-row, provisioned EC2) are absent. The 2 is the honest "right service, no sampling" anchor.

**Why 3 was reachable but not delivered:** the v2 prompt didn't ask for Bedrock-invocation sampling or a `cost_drivers` log. Module 10's cost anchor would push this to 3 by adding `metrics.add_metric("cost_per_row_microUSD", ...)`. For Day 3, Cost=2 is the right anchor.

**Closes failure modes:** 6 (cost-blind) — partially, in the sense that the catastrophic per-row Bedrock call is gone.

---

## Failure-mode mapping (Concept 5) — weak → strong

| Mode | Weak triggered? | Strong triggered? | How closed in v2 prompt |
|---|---|---|---|
| 1. Hallucinated APIs | YES (`s3.save_validated_object`) | NO | Explicit "use real boto3 APIs only"; APAC profile via env var. |
| 2. Wrong vocabulary | YES (`order_id`, `transaction_amount`) | NO | Programme schema field list in Context; "forbidden vocabulary" enumerated. |
| 3. Missing error paths | YES (returns 200 on swallow) | NO | Typed exception ladder in Output format; quarantine paths required. |
| 4. Over-abstraction | YES (4-level factory) | NO | "ONE flat function plus pure helpers. No factory pattern." |
| 5. Silent swallow | YES (`except: pass`) | NO | "NEVER bare `except:`. Every catch is typed." |
| 6. Cost-blind | YES (per-row Bedrock) | PARTIAL | "Do NOT call Bedrock anywhere in this handler." (Sampling discipline still missing → Cost=2). |

**5 of 6 modes fully closed; 1 partially closed.** Score lift: 5/15 → 14/15.

---

## The teaching moment (Lab 3 debrief at 14:30)

When you walk the cohort through this score, anchor on three observations:

1. **The lift from 5 → 14 is +9 points, almost entirely from prompt refinement, not code refactoring.** Same model. Same Cascade. Same engineer. Different prompt. **This IS the discipline.**

2. **Cost stays at 2, not 3.** A learner who scores it 3 hasn't read the anchors carefully — there's no sampling, no cost measurement. Honest scoring trains the calibration eye.

3. **The diff between v1-implicit and v2 is captured in `reviews/m3-prompt-refinement-diff.md`.** Read it as part of the debrief. The lines that close failure mode 5 (silent swallow) are the same lines that drive Observability from 0 → 3.

---

## Next iteration — what would lift Cost to 3

If a learner asks "how do I score 15/15 next time?":

1. Add a `cost_drivers` log line per invocation: `logger.info("cost_observation", extra={"rows": N, "ddb_writes": M, "s3_puts": K})`.
2. Add an EMF metric `cost_per_thousand_rows_microUSD` (computed using a static rate constant from `.windsurfrules`).
3. Add a sampling switch: `if random.random() < SAMPLE_RATE: do_extra_check(row)` for non-mandatory enrichments.

But that's a Module 10 lift, not a Module 3 lift. **For Module 3, 14/15 is the right ceiling.**

---

*Source: Day 1 Concept 6 (5-dim 0–3), Day 3 Concept 5 (6 failure modes). Pass bar: ≥12/15 AND every dim ≥2.*
