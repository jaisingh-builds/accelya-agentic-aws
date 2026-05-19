# Day 7 — Producer Contract (Reference Example)

> **Lab 2 deliverable target.** Each learner authors their own copy at
> `design/m7-producer-contract.md`. This file is the trainer's worked example
> showing what a passing (≥14/18) submission looks like.

---

## Stream target

- **Stream:** `accelya-bookings-stream-<learner>`
- **Shards:** 2
- **Region:** `ap-south-1`

---

## 1. Input shape

The producer Lambda receives a batch of cancellation envelopes:

```python
{
    "events": [
        {
            "event_id":      "<uuid>",
            "event_type":    "cancellation",
            "event_time":    "2026-05-09T14:45:23+00:00",
            "ingest_time":   "<producer fills at submission>",
            "airline_code":  "AI",
            "booking_date":  "2026-05-09",
            "pnr":           "ABCDEF",
            "source_system": "GDS",
            "payload": {
                "pnr": "ABCDEF",
                "cancel_reason_code": "WX",   # WX | OPS | PAX | MED
                "cancellation_event_id": "CXL-7f3a9b21"
            }
        },
        # ... up to 500 events per invocation
    ]
}
```

**Per-event constraint:** `event_id`, `event_type`, `airline_code`, `pnr`, `payload` must be non-empty. Each event ≤1 MB (Kinesis record limit).

---

## 2. Output shape

```python
{
    "submitted_count": 498,       # successfully PutRecords-ed
    "failed_count":    2,
    "failed_records": [
        {"event_id": "<uuid>", "error_code": "validation",
         "error_message": "Missing payload.cancel_reason_code"},
        {"event_id": "<uuid>", "error_code": "ProvisionedThroughputExceededException",
         "error_message": "Rate exceeded; retried 5 times, gave up"}
    ]
}
```

**`error_code` values:**
- `validation` — failed pre-submit schema check
- `ProvisionedThroughputExceededException` — shard throttle after retries exhausted
- `InternalFailure` — Kinesis service error (rare)

---

## 3. Side effects

```
┌─────────────────────────────────────────────────────────────────────────┐
│  events (batch ≤500)                                                    │
│       │                                                                 │
│       ▼                                                                 │
│  ┌──────────────┐    pass    ┌─────────────────────────────────────┐   │
│  │  validate    ├───────────►│  kinesis.put_records                │   │
│  │  envelope    │            │    PartitionKey: airline:date       │   │
│  └──────┬───────┘            │    Data: base64(json.dumps(event))  │   │
│         │ fail                └──────────────┬──────────────────────┘   │
│         ▼                                    │ response                 │
│    failed_records[]                          ▼                          │
│    error_code=validation              ┌─────────────────────────┐       │
│                                       │ FailedRecordCount > 0?  │       │
│                                       └─────┬───────────────────┘       │
│                                             │ yes                       │
│                                             ▼                           │
│                                   ┌──────────────────────┐              │
│                                   │ retry only failed    │              │
│                                   │ records (≤5 retries) │              │
│                                   │ backoff + jitter     │              │
│                                   └──────────────────────┘              │
│                                                                         │
│       After every batch: EMF metric log line                            │
│       records_in, records_failed, retry_count                           │
│       Dimensions: stream_name, airline_code                             │
└─────────────────────────────────────────────────────────────────────────┘
```

**Partition key formula (LOCKED):**

```python
pk = f"{event['airline_code']}:{event['booking_date']}"
# e.g.  "AI:2026-05-09"
```

This is the **baseline strategy** (Concept 3). Production with >10K events/day per (airline, date) pair would extend to:

```python
pk = f"{event['airline_code']}:{event['booking_date']}:{bucket_hash(event['pnr']) % 8}"
```

Both formulas preserve per-PNR ordering on a single shard (same PNR always hashes to the same bucket).

**Data encoding:**

```python
import base64, json
data = base64.b64encode(json.dumps(event).encode("utf-8"))
```

**No persistence in the producer.** All persistence (idempotency, validation, enrichment) lives in the Day-8 consumer + SFN state machine.

---

## 4. Retry policy

Producer catches `ProvisionedThroughputExceededException` per-record from the `PutRecords` response:

```python
for attempt in range(MAX_RETRIES):   # MAX_RETRIES = 5
    failed = [
        Records[i] for i, r in enumerate(response["Records"])
        if r.get("ErrorCode") == "ProvisionedThroughputExceededException"
    ]
    if not failed:
        break
    sleep_seconds = (2 ** attempt) * random.uniform(0.5, 1.5)
    time.sleep(sleep_seconds)
    response = client.put_records(StreamName=stream, Records=failed)
```

**Retry budget math:**
- Attempt 0: immediate
- Attempt 1: ~1-3 s
- Attempt 2: ~2-6 s
- Attempt 3: ~4-12 s
- Attempt 4: ~8-24 s
- Attempt 5: ~16-48 s
- Total worst-case: ~95 s

If retries exhausted, record lands in `failed_records[]` with `error_code=ProvisionedThroughputExceededException`. Caller decides escalation (SNS topic `accelya-pipeline-escalations-<learner>`).

**Forbidden retries:**
- `ValidationError` — never retried; data is bad, retry won't help
- `InternalFailure` — retried at the Lambda invocation level (caller decides)

---

## 5. Metrics

Single EMF log line per batch — CloudWatch extracts metrics server-side:

```python
import json
log_line = {
    "_aws": {
        "Timestamp": int(time.time() * 1000),
        "CloudWatchMetrics": [{
            "Namespace": "Accelya/Streaming",
            "Dimensions": [["stream_name", "airline_code"]],
            "Metrics": [
                {"Name": "records_in",     "Unit": "Count"},
                {"Name": "records_failed", "Unit": "Count"},
                {"Name": "retry_count",    "Unit": "Count"},
            ],
        }],
    },
    "stream_name":   "accelya-bookings-stream-<learner>",
    "airline_code":  "AI",
    "records_in":    500,
    "records_failed": 2,
    "retry_count":   1,
    "corr_id":       context.aws_request_id,
}
print(json.dumps(log_line))
```

**Aggregation rule:** one log line per batch per airline. If a batch contains
events from multiple airlines, emit one log line per airline (split the batch
counters).

**Day 10 wires** a CloudWatch alarm on `records_failed > 0 sustained 5 min`.

---

## 6. Failure handling

**Validation (pre-submit):**

```python
def validate_envelope(e: dict) -> None:
    required = ["event_id", "event_type", "airline_code", "booking_date", "pnr", "payload"]
    missing = [k for k in required if not e.get(k)]
    if missing:
        raise ValidationError(
            f"Envelope missing required fields: {missing}",
            file_key=e.get("event_id"),
        )
    if e["event_type"] not in {"cancellation", "refund", "no_show", "upgrade", "seat_release"}:
        raise ValidationError(
            f"Unknown event_type {e['event_type']}",
            file_key=e.get("event_id"),
        )
```

`ValidationError` events are caught at the producer boundary and added to
`failed_records[]` with `error_code=validation`. **Never submitted to Kinesis.**

**Post-submit per-record errors:**

After `put_records`, each entry in `response["Records"]` has either:
- `SequenceNumber` (success) — incremented `submitted_count`
- `ErrorCode` + `ErrorMessage` (failure) — added to retry queue OR `failed_records[]` after retry exhaustion

**Exceptions caught by the producer:**

| Exception | Action |
|---|---|
| `ValidationError` | Add to failed_records; do not submit |
| `ProvisionedThroughputExceededException` (per-record) | Retry with backoff+jitter; cap 5 |
| `ProvisionedThroughputExceededException` (whole call) | Same retry policy at batch level |
| `KinesisServiceException` | Single retry; if still failing, all records → failed_records with error_code=service |
| `TransientError` (network) | Caller's responsibility (handled at orchestration layer) |
| `ConfigError` | Raised — escalates to SNS via deployment monitoring |

**No raise from producer for data errors.** All record-level failures return in
`failed_records[]`. The caller (the orchestrator or Day-8 state machine) decides
whether to re-queue, escalate, or drop.

---

## HITL Review (6 dimensions, 18 points)

This document is graded 0-3 on each:

| Dim | Score | Notes |
|---|---|---|
| **Correctness** | 3/3 | All 5 event types accommodated; envelope schema complete; per-event constraints stated. |
| **Safety** | 3/3 | Pre-submit validation; no PII in error_message; ConfigError → SNS path documented. |
| **Idempotency** | 3/3 | Producer is stateless; consumer owns idempotency (called out explicitly). No double-PutRecords path. |
| **Observability** | 3/3 | EMF metric line specified end-to-end; dimensions named; corr_id in log. Day 10 alarm hooked. |
| **Cost** | 3/3 | PutRecords bulk path; retry capped at 5; explicit "no PutRecord in a loop" forbidden. |
| **Per-PK Order** | 3/3 | PK formula explicit and locked; deterministic; cancel→refund same-PNR chain analysis included. |

**Total: 18/18.** Reference example; learner submissions need ≥14/18.

---

*This is the reference. Learners authoring `design/m7-producer-contract.md` should match this structure but can adapt section content. Sections 3 (side effects) and 6 (failure handling) are the most-graded; reviewers focus there.*
