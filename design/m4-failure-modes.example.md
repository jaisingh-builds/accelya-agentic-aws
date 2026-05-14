# M4 — Failure Modes (Reference Example)

> **Trainer reference.** Lab 2 deliverable: 5 file-based traces + 1 source-outage design section.
> Learner artefact: `design/m4-failure-modes.md` on `module-4-<learner>`.

---

## 01 — Schema drift

### Synthetic file
`data/m4-failures/01-schema-drift.json`

### What's broken
Row 47 has `fare_currency` instead of `currency`. Row 89 has `fare_amount: "2845.0"` (string instead of number).

### Catch point
`schema_check(row)` in `src/validator/handler.py`. After parsing the row, before idempotency check.

### Quarantine path
`s3://accelya-airline-data-ap-south-1/quarantine/<learner>/schema_drift/2026-05-08/01-schema-drift.json:47`

### Sidecar JSON
```json
{
  "reason": "schema_drift",
  "field_diff": ["+fare_currency", "-currency"],
  "expected_schema_version": "v1.2.0",
  "row_data": { /* original row preserved */ },
  "source_file": "raw/synthetic/m4-failures/01-schema-drift.json",
  "line_no": 47,
  "correlation_id": "a1b2c3d4-...",
  "validator_version": "m5-v1"
}
```

### Log line
```json
{"ts":"2026-05-08T10:14:32Z","level":"WARN","corr_id":"a1b2c3d4-...","function":"validator","event":"row_quarantined","reason":"schema_drift","key":"raw/synthetic/m4-failures/01-schema-drift.json","line_no":47}
```

### Operator action
1. Open `s3://.../quarantine/<learner>/schema_drift/2026-05-08/01-schema-drift.json:47.sidecar.json`.
2. Read `field_diff`: source has new `fare_currency` field; schema expects `currency`.
3. Decide: (a) coerce in validator (`fare_currency` → `currency`), (b) extend schema, or (c) reject upstream change.
4. Update validator + schema; redeploy; replay quarantined rows.

---

## 02 — Partial write

### Synthetic file
`data/m4-failures/02-partial.json`

### What's broken
File is truncated mid-row (drops at row 31 of 100). JSON parser fails on EOF in middle of object.

### Catch point
`manifest_row_count_check()` in `src/lander/handler.py`. Compares `raw_manifest.row_count` to `validated_count + quarantined_count + duplicate_skipped`.

### Quarantine path
`s3://.../quarantine/<learner>/partial/2026-05-08/02-partial.json`

### Sidecar JSON
```json
{
  "reason": "partial",
  "expected_rows": 100,
  "actual_parsed_rows": 30,
  "delta": 70,
  "source_file": "raw/synthetic/m4-failures/02-partial.json",
  "correlation_id": "...",
  "validator_version": "m5-v1"
}
```

### Log line
```json
{"ts":"...","level":"ERROR","corr_id":"...","function":"lander","event":"partial_write_detected","key":"raw/...","expected":100,"actual":30}
```

### Operator action
1. Check upstream manifest matches file size.
2. Request re-send from BSP.
3. Once re-sent file arrives (different key), idempotency guards (`file#`) skip the truncated file.

---

## 03 — Duplicate ingest

### Synthetic file
`data/m4-failures/03-duplicate.json`

### What's broken
Nothing is "broken" — the file is a byte-identical re-send of an earlier file already processed.

### Catch point
`claim('file#' + file_sha256, ttl_days=90)` in `src/validator/handler.py`. ConditionalCheckFailedException → duplicate.

### Lands in
**NOT quarantine.** DynamoDB no-op. Validator returns `outcome: "duplicate"`.

### Sidecar JSON
N/A — duplicates don't produce sidecar files.

### Log line
```json
{"ts":"...","level":"INFO","corr_id":"...","function":"validator","event":"duplicate_skipped","reason":"file_byte_hash_match","key":"raw/...","file_sha256":"e3b0c44..."}
```

### Operator action
Usually none — duplicates are normal (retries, re-sends, network drops). Audit log shows the skip; if frequency is unusual, investigate upstream.

**Note:** for row-reordered or reformatted duplicates, the canonical_manifest_hash guard catches them. For same-business-event re-arrivals (different file packaging), the business#settlement_id guard catches them.

---

## 04 — Late event

### Synthetic file
`data/m4-failures/04-late-event.json`

### What's broken
Nothing is "broken" — rows are valid, fields parse correctly, business rules pass. But `issue_date` is 95 days ago; `event_date` is today's `ingest_date`.

### Catch point
`event_date_check(row)` in `src/validator/handler.py`. If `(ingest_date - event_date) > 30 days`, flag as late.

### Lands in
**NOT quarantine.** `validated/<learner>/<source>/<date>/<file>.jsonl` with each row having `is_late: true`.

### Sidecar JSON
N/A — late events are valid; they get a flag, not a sidecar.

### Log line
```json
{"ts":"...","level":"INFO","corr_id":"...","function":"validator","event":"late_event_flagged","key":"raw/...","line_no":12,"is_late":true,"event_date":"2026-02-15","ingest_date":"2026-05-08","delay_days":82}
```

### Operator action
Usually none — late events are normal in airline data (90-day refund window). Day 6's curator preserves `is_late` and `event_date` as columns; analytics filters when needed.

---

## 05 — Malformed row

### Synthetic file
`data/m4-failures/05-malformed.json`

### What's broken
Row 14 has unescaped quotes inside a string field. Row 67 has trailing comma. Row 88 has UTF-16 byte sequence in the middle of a UTF-8 file.

### Catch point
`json.loads(line)` raises `JSONDecodeError` in `src/validator/handler.py`. Before any schema check.

### Quarantine path
`s3://.../quarantine/<learner>/malformed/2026-05-08/05-malformed.json:14`

### Sidecar JSON
```json
{
  "reason": "malformed",
  "error_type": "JSONDecodeError",
  "error_message": "Expecting ',' delimiter: line 14 column 89",
  "raw_bytes_preserved": "...the actual bytes...",
  "source_file": "raw/synthetic/m4-failures/05-malformed.json",
  "line_no": 14,
  "correlation_id": "...",
  "validator_version": "m5-v1"
}
```

### Log line
```json
{"ts":"...","level":"WARN","corr_id":"...","function":"validator","event":"row_quarantined","reason":"malformed","key":"raw/...","line_no":14,"error":"JSONDecodeError"}
```

### Operator action
1. Inspect raw bytes in sidecar (encoding issues may need hex viewer).
2. Determine if upstream serialiser is broken or if file got corrupted in transit.
3. Request re-send from BSP if upstream issue; flag the file's source path if persistent.

---

## 06 — Source-system outage  ← DESIGN-ONLY, NOT FILE-BASED

### What's not there
No file. The BSP feed expected at `s3://accelya-airline-data-ap-south-1/raw/BSP/2026-05-08/` did not arrive by the expected window (every Tuesday 02:00-04:00 UTC).

### Catch mechanism
**EventBridge scheduled rule** fires every weekday at 04:30 UTC:
```yaml
SourceOutageChecker:
  Type: AWS::Events::Rule
  Properties:
    ScheduleExpression: "cron(30 4 ? * TUE-FRI *)"
    Targets:
      - Arn: !GetAtt SourceCheckerLambda.Arn
        Id: source-outage-checker
```

The `source-checker` Lambda:
1. Lists objects under `raw/BSP/<today>/`.
2. If empty AND today is Tuesday-Friday → publish to `accelya-pipeline-alerts` SNS topic.
3. SNS topic subscribers: on-call PagerDuty, ops email distribution list.

### Lands in
**Neither validated/ nor quarantine/.** This is an operational alert, not a row-level failure. The Lambda execution itself logs:

```json
{"ts":"...","level":"ERROR","corr_id":"...","function":"source-checker","event":"source_outage","source":"BSP","expected_window_start":"2026-05-08T02:00Z","check_time":"2026-05-08T04:30Z","files_found":0}
```

### Operator action
1. Page received via PagerDuty / SNS.
2. Contact BSP upstream operations.
3. If catch-up file arrives later → late-event handling (Mode 04) absorbs the delayed rows. `is_late=true` flag preserves the late-arrival fact for downstream reporting.
4. If BSP confirms cycle is missing entirely → log incident; settlement reconciliation team uses prior week's data.

### Why NOT in quarantine
Quarantine implies "data arrived but failed validation; preserve for inspection." Source outage = no data arrived. There's nothing to preserve. The alert IS the artefact.

---

## Summary

| # | Category | Lands in | Pages on-call? |
|---|---|---|---|
| 01 | Schema drift | `quarantine/<learner>/schema_drift/` | No (operator follows up async) |
| 02 | Partial write | `quarantine/<learner>/partial/` | No |
| 03 | Duplicate ingest | DynamoDB no-op | No (audit log only) |
| 04 | Late event | `validated/` with `is_late=true` | No |
| 05 | Malformed row | `quarantine/<learner>/malformed/` | No |
| 06 | Source outage | SNS topic → on-call | **Yes** |

**Three quarantine categories** (01, 02, 05). **Two non-quarantine valid handling** (03, 04). **One alert-only** (06). Total 6 failure modes, 4 disposition outcomes.

---

*Reference catalogue. Learners produce their own version in Lab 2. Trainer compares for calibration; especially watches for 03/04 being incorrectly quarantined.*
