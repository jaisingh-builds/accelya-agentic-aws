# HITL_REVIEW — src/weak_validator/handler.py

> **This is the REFERENCE scorecard** for the Day 3 Lab 3 anti-example.
> Trainer-only reference. Learners produce their own scorecard during the lab — discrepancies are the teaching moment.

---

**Artefact:** `src/weak_validator/handler.py`
**Reviewer:** Jai Singh (trainer reference)
**Date:** 2026-05-11 (Day 0 / pre-delivery anchor)
**Module:** M3
**Lab:** Lab 3 (weak-vs-strong critique)

---

## The score (0–3 per dim · PASS = ≥12/15 AND every dim ≥2)

| Dim            | Score | Evidence (one line per dim)                                                                 |
|----------------|-------|---------------------------------------------------------------------------------------------|
| Correctness    | **2** | Happy path *looks* right for the made-up shape; missing edge cases for malformed payload.   |
| Security       | **1** | Mid-grade — uses raw model ID + no IAM scoping visible. Mode 1: hallucinated S3 API.         |
| Observability  | **0** | `except: pass` swallows all errors. No log lines. No correlation_id. No metrics.            |
| Scalability    | **1** | `body.read()` loads the whole file into memory. Non-idempotent (no dedup key).              |
| Cost           | **1** | Right service (Lambda), wrong discipline: synchronous Bedrock call PER ROW.                 |
| **TOTAL**      | **5/15** | **REVISE** — Observability=0 alone fails the per-dim ≥2 rule.                            |

**Verdict:** REVISE
**Min dim:** Observability = 0 (PASS requires every dim ≥ 2)

---

## Per-dimension detail

### Correctness — `2/3`

**Anchors:**
- 3 — matches spec + edge cases tested
- 2 — matches spec; happy path only
- 1 — matches spec but missing field or wrong API name
- 0 — doesn't compile / hallucinated APIs

**Why 2 (not 1):** the handler *does* call valid AWS APIs for the happy path (`s3.get_object`, `bedrock.converse`). It would actually run for one well-formed file. **But** Mode 1 (hallucinated `s3.save_validated_object`) means the only success branch can never succeed at runtime — which arguably drops this to 1.

Trainer note: defensible at 1 or 2; mark this as a calibration discussion point.

**Evidence:**
- `s3.save_validated_object(...)` does not exist in boto3 — this is hallucinated. **Mode 1**.
- Field names `order_id` and `transaction_amount` are NOT the programme schema (`pnr`, `airline_code`, `fare_amount`). **Mode 2** (wrong vocabulary).

---

### Security — `1/3`

**Anchors:**
- 3 — ARN-scoped IAM + named verbs + Conditions; secrets via env; PII tagged
- 2 — no wildcards; secrets via env; PII not addressed
- 1 — some wildcards present
- 0 — `Action: "*"` / hardcoded secrets

**Why 1:** No IAM policy is shown in the handler itself, but the `boto3` clients made would need to be backed by a permissive role. The model ID is the **raw `anthropic.claude-3-5-sonnet-20241022-v2:0`** instead of the APAC inference profile — this fails from ap-south-1 and exposes the wrong cross-region routing.

**Evidence:**
- `modelId="anthropic.claude-3-5-sonnet-20241022-v2:0"` — raw model ID; not the locked APAC profile.
- No PII tagging visible. The handler dumps the full row into the Bedrock prompt — could leak PII to a model that doesn't strictly need it.
- No IAM scoping at code level (defensive coding).

---

### Observability — `0/3`  ← THE FAIL-OUT-RIGHT DIM

**Anchors:**
- 3 — powertools Logger + correlation_id + EMF + classified errors
- 2 — JSON logs + classified errors; no metrics yet
- 1 — JSON logs only
- 0 — `print` statements / silent `except: pass`

**Why 0:** the entire body is wrapped in `except Exception: pass`. Schema failures, network failures, AWS-side throttling — all swallowed silently. The function returns `statusCode: 200` regardless. **No log line ever fires on failure.** This is the textbook Concept-5 Mode 5.

**Evidence:**
- `except Exception: pass` — **Mode 5** (silent swallow).
- No `aws_lambda_powertools.Logger` anywhere.
- No `correlation_id` propagated from the Lambda context.
- No EMF metric emitted.
- Returns 200 on every code path (including the silent-fail path).

**This single drop is what makes the artefact REVISE regardless of other scores.**

---

### Scalability — `1/3`

**Anchors:**
- 3 — idempotent + bounded memory + maintainable + tested at 10× scale
- 2 — idempotent + bounded; maintainability OK
- 1 — idempotent only — or partial fixes only
- 0 — unbounded memory, non-idempotent, OR over-abstracted

**Why 1 (not 0):** Two reasons it nearly drops to 0:
- `body.read()` loads the entire S3 object into memory. At 50–80 MB per file this fits, but at 10× scale (500 MB) it OOMs the Lambda. **Mode 4-ish**.
- Non-idempotent: re-running on the same file double-writes via `s3.save_validated_object`. No `claim('row#<key>:<line>')` pattern.
- 4 layers of indirection (`HandlerFactoryProvider → HandlerFactory → ValidatorHandlerBase.process → _process_event_internal`) for a 30-line problem. **Mode 4** (over-abstraction).

The "1" is generous: the per-row loop *could* theoretically support partial replay if the over-abstraction were stripped. A learner scoring 0 here is defensible.

**Evidence:**
- `obj["Body"].read()` — full read; not streaming.
- No idempotency keys in DynamoDB.
- 4-level class hierarchy with no behavioural value.

---

### Cost — `1/3`

**Anchors:**
- 3 — workload-appropriate service + sampled where applicable + cost-per-record measurable
- 2 — workload-appropriate service; no sampling discipline
- 1 — workload-appropriate; cost not considered
- 0 — wrong service for the workload

**Why 1:** Lambda is the right service for a 50 MB file. **But:** synchronous Bedrock call per row is catastrophic cost discipline. For a 10K-row file you'd issue 10K Bedrock invocations — the programme cap is 50 per session. Even at $0.012/call you've burned the per-session budget on one file. **Mode 6** (cost-blind).

**Evidence:**
- `for row in data: bedrock.converse(...)` — one invocation per row. No batching, no sampling.
- No `cost_drivers` documented anywhere.
- No CloudWatch metric to track `bedrock_invocations_per_file`.

---

## Failure-mode mapping (Concept 5)

| Mode | Triggered? | Lines | HITL dim hit |
|------|-----------|-------|--------------|
| 1. Hallucinated APIs | **YES** | `s3.save_validated_object(...)` | Correctness |
| 2. Wrong vocabulary | **YES** | `order_id`, `transaction_amount` | Correctness |
| 3. Missing error paths | **YES** | Returns 200 on swallow | Observability + Correctness |
| 4. Over-abstraction | **YES** | 4-level class hierarchy | Scalability (maintainability) |
| 5. Silent swallow | **YES** | `except: pass` | Observability |
| 6. Cost-blind | **YES** | per-row Bedrock call | Cost |

**All 6 modes triggered.** The artefact is the perfect anti-example. Pass-bar verdict: REVISE.

---

## Next iteration — what the v2 prompt must close

(See `prompts/v2_validator.txt` for the actual refined prompt.)

1. **Correctness** — explicit programme schema (`pnr`, `airline_code`, `fare_class`, `od_pair`, `settlement_date`). No `order_id`. Use real boto3 APIs only.
2. **Security** — APAC inference profile (`apac.anthropic.claude-3-5-sonnet-20241022-v2:0`). Named IAM actions + ARN-scoped. No PII in prompts.
3. **Observability** — `aws_lambda_powertools.Logger` with `correlation_id`. Classified errors via `PipelineError` ladder. EMF metric `records_invalid`.
4. **Scalability** — line-by-line streaming. Idempotency claims (`row#<key>:<line>`). Flat handler, no factories.
5. **Cost** — Bedrock OUT of the row loop. If Bedrock needed at all, batch + sample. Otherwise pure Python schema check.

---

*Source: Day 1 Concept 6 (5-dim 0–3 HITL scoring), Day 3 Concept 5 (6 failure modes). Pass bar: ≥12/15 AND every dim ≥2.*
