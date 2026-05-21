# HITL_REVIEW — design/m7-producer-contract.md

> **Reference scorecard** for Module 7 Lab 2 (producer contract design).
> Scored against `design/m7-producer-contract.example.md` (trainer worked example).
> Learners copy this structure, replace scores/evidence for their own `design/m7-producer-contract.md`, and have a pair partner sign.

---

**Artefact:** `design/m7-producer-contract.md` (reference: `design/m7-producer-contract.example.md`)
**Reviewer:** `<pair-partner-github-handle>`
**Date:** 2026-05-21
**Module:** M7
**Lab:** Lab 2 (producer contract design)

---

## The score (0–3 per dim · PASS = ≥17/21 AND every dim ≥2)

| Dim | Score | Evidence (one line per dim) |
|-----|-------|-----------------------------|
| Correctness | **3** | Five event types + envelope constraints; batch ≤500; PutRecords response handling complete. |
| Safety | **3** | Pre-submit validation; no PII in `error_message`; ConfigError → SNS escalation path named. |
| Idempotency | **3** | Producer stateless; consumer owns `stream#name#shard#seq` claim — no producer-side dedup table. |
| Observability | **3** | EMF line with `records_in` / `records_failed` / `retry_count`; `corr_id`; Day 10 alarm hook. |
| Cost | **3** | `put_records` bulk only; retry cap 5; forbidden `put_record` loop; shard-quota awareness stated. |
| Schema Discipline | **3** | Locked envelope fields; `event_type` whitelist; programme vocabulary (`pnr`, not `order_id`). |
| Per-PK Ordering | **3** | PK `airline_code:booking_date` locked; cancel→refund ordering + hash-bucket extension documented. |
| **TOTAL** | **21/21** | **PASS** |

**Verdict:** PASS

**Module 7 pass bar:** ≥17/21 **and** every dimension ≥2/3.

---

## Per-dimension detail

### Correctness — `3/3`

**Anchors:**
- **3** — All programme event types; input/output contracts complete; retry and post-submit paths specified; Kinesis limits respected (≤500 records, ≤1 MB/record).
- **2** — Happy path + main failure paths; one edge case missing (e.g. whole-call throttle).
- **1** — Contract shape OK but wrong API (`put_record` loop) or missing output fields.
- **0** — Wrong service model or non-compiling pseudocode with hallucinated APIs.

**Evidence:**
- Input batch envelope with `events[]` up to 500; per-event non-empty checks and 1 MB limit stated.
- Output documents `submitted_count`, `failed_count`, `failed_records[]` with `error_code` ∈ `{validation, ProvisionedThroughputExceededException, InternalFailure}`.
- Retry loop indexes failed entries from `PutRecords` response only — not whole-batch blind retry.
- Side-effects diagram shows validate → put_records → per-record retry branch.
- Explicit: no persistence in producer (validation/enrichment deferred to Day 8 consumer + SFN).

---

### Safety — `3/3`

**Anchors:**
- **3** — Pre-submit validation rejects bad data before Kinesis; no PII in logs/errors; escalation path for config failures; least-privilege assumptions in contract text.
- **2** — Validation present; PII not addressed in error paths.
- **1** — Post-submit-only validation or leaky error messages.
- **0** — Submits unvalidated payloads; logs full PNR/payload at INFO.

**Evidence:**
- `ValidationError` never retried — bad data cannot pollute the stream.
- `error_message` limited to field names / error codes — no passenger-identifying payload in failure objects.
- `ConfigError` raises to SNS / deployment monitoring — not swallowed into `failed_records`.
- Forbidden: submitting then quarantining (validation must be **before** `PutRecords`).

---

### Idempotency — `3/3`

**Anchors:**
- **3** — Producer stateless; consumer idempotency key and claim-before-side-effect called out; no duplicate-submit paths.
- **2** — Stateless producer stated; consumer idempotency vague.
- **1** — Producer writes dedup state or retries whole batch blindly.
- **0** — Double-emit on retry without sequence awareness.

**Evidence:**
- Section 3: “No persistence in the producer.”
- Day 8 consumer contract referenced: key `stream#<name>#<shard>#<sequence_number>` (not file_key+line_no).
- Retries re-submit **only** failed indices from the prior `PutRecords` response — not the full batch.
- Producer does not touch `stream_seen_keys_<learner>` — DDB table is consumer-owned (Lab 1 provision).

---

### Observability — `3/3`

**Anchors:**
- **3** — EMF metrics + `corr_id` + classified errors + alarm hook named.
- **2** — JSON logs + error classes; no EMF or no dimensions.
- **1** — Unstructured logs only.
- **0** — Silent failures / `except: pass`.

**Evidence:**
- EMF log line spec: namespace `Accelya/Streaming`, metrics `records_in`, `records_failed`, `retry_count`.
- Dimensions: `stream_name`, `airline_code` — enables per-airline breakdown (not a single global counter).
- `corr_id` = `context.aws_request_id` in the metric payload.
- Day 10 alarm: `records_failed > 0` sustained 5 min — forward reference is explicit.
- Exception table maps each failure class to a visible outcome (failed_records vs raise).

---

### Cost — `3/3`

**Anchors:**
- **3** — Bulk API, bounded retries, hot-shard awareness, measurable cost drivers (records/shard/API calls).
- **2** — Bulk path + retry cap; no shard-quota or batch-size discipline.
- **1** — Correct service (Kinesis) but `put_record` per event.
- **0** — Wrong service or unbounded retry storm.

**Evidence:**
- **Forbidden:** `put_record` in a loop (Lab 3 pedagogy uses it; production contract forbids it).
- `PutRecords` batches up to 500 — minimizes API calls vs per-record puts.
- Retry cap 5 with exponential backoff + jitter; worst-case ~95 s documented — bounded spend.
- PK strategy notes hot-shard risk at scale and documents hash-bucket extension — cost of skew called out.
- No Bedrock in producer — inference cost isolated to Day 8 enrich path.

---

### Schema Discipline — `3/3`

**Anchors:**
- **3** — Envelope schema locked; event_type whitelist; programme field names; payload nested correctly; evolution note if present.
- **2** — Required fields listed; one naming drift (`order_id`) or missing event type.
- **1** — Informal “JSON blob” without whitelist or constraints.
- **0** — Ad-hoc schema per event; incompatible with curated lake contracts.

**Evidence:**
- Required top-level keys: `event_id`, `event_type`, `airline_code`, `booking_date`, `pnr`, `payload`.
- `event_type` ∈ `{cancellation, refund, no_show, upgrade, seat_release}` — matches STREAM CONTEXT / v10 prompt.
- Payload uses programme vocabulary: `pnr`, `cancel_reason_code`, not generic `order_id` / `customer_id`.
- `ValidationError` cites `file_key=event_id` — ties into Day 5+ exception ladder pattern.
- Encoding: `base64(json.dumps(event))` — matches Kinesis Data plane contract.

---

### Per-PK Ordering — `3/3`

**Anchors:**
- **3** — Deterministic PK formula locked; cancel→refund same-PNR ordering explained; `SequenceNumberForOrdering` or equivalent noted; hash extension preserves order within bucket.
- **2** — Deterministic PK; ordering chain mentioned without strict-ordering mechanism.
- **1** — Low-cardinality PK (`airline_code` only) or random UUID PK.
- **0** — Random/static PK — destroys per-PNR sequencing.

**Evidence:**
- **Locked PK:** `pk = f"{airline_code}:{booking_date}"` — not UUID, not static `"cancellation"`.
- Lab 3 ordering test: cancel + refund on `'AI:2026-05-09'` → same shard, refund `SequenceNumber` > cancel (strict ordering flag in lab guide).
- Production extension: `{airline}:{date}:{bucket_hash(pnr) % 8}` — adds cardinality without breaking per-PNR order within bucket.
- Explicit contrast: random `event_id` PK distributes bytes but **loses** cancel→refund ordering — named as anti-pattern.
- Aligns with `.windsurfrules` v4 STREAM CONTEXT forbidden list (no `uuid4`, no static PK).

---

## Module 7 scope checklist (Labs 1–3)

Use this alongside the producer-contract score when signing the full day:

| Lab | Artefact | 7-dim focus |
|-----|----------|-------------|
| Lab 1 | `reviews/m7-provision-evidence.md` | Cost (2 shards, 24h retention), Safety (IAM role scope), Idempotency (DDB TTL on `ttl`) |
| Lab 2 | `design/m7-producer-contract.md` | **This review** — all 7 dims |
| Lab 3 | `reviews/m7-hot-shard-evidence.md` | Per-PK Ordering (primary), Cost (shard `IncomingBytes` distribution) |

---

## If REVISE: what to change

1. **Per-PK Ordering** — Replace UUID or static PK with `airline_code:booking_date`; add one paragraph on cancel→refund ordering on the same shard.
2. **Schema Discipline** — Add `event_type` whitelist and rename any `order_id` → `pnr`.
3. **Cost** — Replace per-record `put_record` loop with `put_records` batches; cap retries at 5.
4. **Safety** — Move validation before `PutRecords`; strip PNR from `error_message`.
5. **Observability** — Add EMF template with `stream_name` + `airline_code` dimensions.

**Next iteration prompt addition (for Cascade):**

```
REVIEW NOTES — M7 producer contract:
- PartitionKey MUST be f"{airline_code}:{booking_date}" — never uuid4() or static string.
- Use put_records only (max 500); retry failed indices only; max 5 retries with jitter.
- Validate envelope BEFORE PutRecords; ValidationError → failed_records, never submitted.
- EMF: records_in, records_failed, retry_count; dimensions stream_name, airline_code; include corr_id.
- Producer is stateless; idempotency key stream#name#shard#seq is consumer-owned.
- Document cancel-then-refund ordering on same PK; mention SequenceNumberForOrdering for strict order.
```

---

## Dimension map (programme context)

| # | Dimension | Introduced | M7 application |
|---|-----------|------------|----------------|
| 1 | Correctness | D3 | Contracts, event types, Kinesis limits |
| 2 | Safety | D3 | Pre-submit validation, PII, escalation |
| 3 | Idempotency | D3 | Stateless producer; seq-based consumer claim |
| 4 | Observability | D3 | EMF + corr_id + alarms |
| 5 | Cost | D3 | PutRecords batching, retry cap, shard skew |
| 6 | Schema Discipline | D5 | Envelope + event_type whitelist |
| 7 | Per-PK Ordering | **D7** | PK formula + ordering test (replaces Query Cost for non-SQL artefacts) |

> **Note:** Cumulative programme checklist adds **Query Cost Discipline** (D6) for Athena/SQL artefacts. For Module 7 streaming design, **Per-PK Ordering** is the 7th dimension. Do not score producer contracts on `SELECT *` or partition filters — score shard/PK cost discipline under **Cost** and **Per-PK Ordering** instead.

---

*Pass bar: ≥17/21 AND every dim ≥2. Reference example scores 21/21; learner submissions typically target ≥18/21 after pair review.*
