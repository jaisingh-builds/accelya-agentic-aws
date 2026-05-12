# HITL_REVIEW — src/validator/handler.py (Module 2)

> **Template.** Copy this to `reviews/HITL_REVIEW-m2-validator.md` and fill in.
> Commit alongside your branch by end of Lab 3.

---

**Artefact:** `src/validator/handler.py`
**Source:** Trainer-provided (Day 2 deck slide 17)
**Deployed to:** `accelya-m2-validator-<your-name>`
**Reviewer:** `<your-github-handle>`
**Date:** YYYY-MM-DD
**Module:** M2
**Lab:** Lab 3

---

## The score (0–3 per dim · PASS = ≥12/15 AND every dim ≥2)

| Dim            | Score | Evidence (one line per dim)                                                          |
|----------------|-------|--------------------------------------------------------------------------------------|
| Correctness    |       |                                                                                      |
| Security       |       |                                                                                      |
| Observability  |       |                                                                                      |
| Scalability    |       |                                                                                      |
| Cost           |       |                                                                                      |
| **TOTAL**      | __/15 |                                                                                      |

**Verdict:** [ ] PASS  [ ] REVISE
**Min dim:** _____ = ___

---

## Per-dimension detail

### Correctness — `<score>/3`

**Anchors:**
- **3** — matches spec + edge cases tested
- **2** — matches spec; happy path only
- **1** — missing field or wrong API name
- **0** — doesn't compile / hallucinated APIs

**Evidence:**
- Real boto3 APIs only (`s3.get_object`, `s3.put_object`). No hallucinated method names.
- `REQUIRED = {"pnr", "airline_code", "fare_class", "od_pair", "settlement_date"}` set in code, lowercase snake_case (programme schema, locked from Day 4).
- Reads JSON, splits into good/bad by `REQUIRED.issubset(row)`.
- **What it does NOT do:** business rules, type checks, value-range checks, duplicate detection. Catches missing-key only — that's why my smoke test caught 1 of 6 deliberate defects in `data/synthetic_ticket_issues.json`. **Acceptable for M2; addressed in M3 (weak vs strong) and M5 (typed validation ladder).**

**My score:** ___/3 because ___.

---

### Security — `<score>/3`

**Anchors:**
- **3** — ARN-scoped IAM + named verbs + Conditions; secrets via env; PII tagged
- **2** — no wildcards; named actions; secrets via env
- **1** — some wildcards present
- **0** — `Action: "*"` / `Resource: "*"` / hardcoded secrets

**Evidence:**
- `BUCKET = os.environ["BUCKET_NAME"]` — bucket name read from env, not hardcoded.
- No long-lived AWS keys in code. IAM role provides credentials via STS at runtime.
- IAM execution role (`accelya-lambda-role-<your-name>`) attached to programme-wide `accelya-program-boundary` — even if Cascade later generates over-permissive policy, the boundary clamps it.
- `os.getenv("APP_VERSION", "m2")` — version string in env, not magic literal.
- **What it does NOT do:** explicit PII tagging on output objects, ARN-scoped Conditions. Acceptable for M2; M10 introduces full PII tagging.

**My score:** ___/3 because ___.

---

### Observability — `<score>/3`

**Anchors:**
- **3** — powertools Logger + correlation_id + EMF + classified errors
- **2** — JSON logs + classified errors; no metrics yet
- **1** — JSON logs only
- **0** — `print` statements / silent `except: pass`

**Evidence:**
- `corr_id = context.aws_request_id` propagated through every log line.
- Structured JSON via `emit()` helper — one log line per event with `ts`, `level`, `event`, plus domain-specific fields.
- Two events logged: `received` (input) and `validated` (output). Both have airline-aware fields (`airline_code`, `key`, `zone`, `records_*`).
- **What it does NOT do:** powertools Logger (M5+), EMF metrics (M10), classified typed-exception ladder (M5). The print-JSON pattern is acceptable for M2 because the JSON shape is parseable in Insights identically to powertools output.

**My CloudWatch Insights query that proved this works:**
```
fields @timestamp, event, records_good, records_bad
| filter corr_id = "<paste-id>"
| sort @timestamp asc
```
Results: <paste output>

**My score:** ___/3 because ___.

---

### Scalability — `<score>/3`

**Anchors:**
- **3** — idempotent + bounded memory + maintainable + tested at 10× scale
- **2** — idempotent + bounded; maintainability OK
- **1** — idempotent only
- **0** — unbounded memory / non-idempotent

**Evidence:**
- **Idempotent:** writes to `validated/.../<same-key>` and `quarantine/.../<same-key>` overwrite cleanly. Replays produce same end-state.
- **Bounded:** 256 MB memory + 30s timeout. Reads one object (~500 KB to 50 MB), writes at most two.
- **What it does NOT do:** streaming reads (loads whole file via `obj["Body"].read()`). For 50 MB this fits; for 500 MB it OOMs. M5 fixes via chunking + Step Functions Map. **Acceptable for M2 because the workload is bounded by the trainer-provided test file size.**
- Single-threaded; one S3 event per invocation. Lambda concurrency caps protect from runaway.

**My score:** ___/3 because ___.

---

### Cost — `<score>/3`

**Anchors:**
- **3** — workload-appropriate service + sampled where applicable + measurable cost-per-record
- **2** — right service; no sampling discipline
- **1** — workload-appropriate; cost not considered
- **0** — wrong service entirely

**Evidence:**
- **Right service:** Lambda for 50 MB batch validation, 250 ms execution. Cost: ~$0.000001 per invocation. For 10K invocations a month, ~$0.01.
- 256 MB memory chosen to bound cost-per-second (cheaper than 1 GB at same speed for this workload).
- 30s timeout caps runaway cost from infinite loops or hangs.
- **What it does NOT do:** Bedrock-invocation sampling (none called), cost-per-record measurement, EMF cost metric. Acceptable for M2 — programme Cost discipline becomes explicit on M10.
- Idempotency means re-invokes are free of double-writes (no duplicate S3 PUTs).

**My score:** ___/3 because ___.

---

## My smoke-test results (Lab 3 step 3-5)

**File uploaded:** `s3://accelya-airline-data-ap-south-1/raw/<your-name>/2026/05/<date>/synthetic_ticket_issues.json` (500 records, 6 deliberate defects)

**Lambda response:**
```
{"statusCode": 200, "good": ___, "bad": ___}
```

**CloudWatch log fields from `event: validated`:**
- `records_total`: ___
- `records_good`: ___
- `records_bad`: ___
- `duration_ms`: ___
- `airline_code`: ___

**S3 outputs:**
- `validated/<your-name>/.../*.json` size: ~___ KB
- `quarantine/<your-name>/.../*.json` size: ~___ KB

---

## Calibration: why didn't bad = 6?

The synthetic data pack has 6 deliberate defects (per `data/README.md`):

| Idx | Defect | Caught? | Why |
|---|---|---|---|
| 7   | Missing `fare_class` | ✅ Yes | REQUIRED.issubset() catches missing key |
| 42  | `airline_code = "XYZ"` (invalid IATA) | ❌ | Key present; value not validated |
| 89  | `fare_amount = "n/a"` (string in numeric) | ❌ | `fare_amount` isn't in REQUIRED |
| 156 | `pnr = ""` (empty string) | ❌ | Key present; value not validated |
| 233 | Duplicate of 232 | ❌ | No idempotency check on row level |
| 401 | Future-dated `settlement_date` | ❌ | No business rule check |

**Catching 1 of 6 is expected for the M2 handler.** Module 3 (weak vs strong validator) and Module 5 (typed validation ladder) close the remaining gaps. **Honest calibration:** the M2 handler is intentionally minimal — there's somewhere to go.

---

## What I'd change in v2 (preview of M3 Lab 3)

If I were lifting this to M5 standard, the prompt I'd write to Cascade would add:
- Programme schema **value validation**, not just key presence (closes defect 42, 89, 156).
- Typed `SchemaError`, `BusinessRuleError`, `DuplicateError` ladder.
- Idempotency claim via DynamoDB `row#<key>:<line>` (closes defect 233).
- Business-rule check on `settlement_date <= today` (closes defect 401).
- Streaming line-by-line via `iter_lines()` instead of full `body.read()`.

That'd push this from ~13/15 to ~15/15 — and is exactly what we build over M3 + M5.

---

*Source: Day 2 Lab 3 (deck slides 26-28). Pass bar: ≥12/15 AND every dim ≥2.*
