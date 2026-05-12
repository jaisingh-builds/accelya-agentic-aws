# Module 2 — Lab 2 S3 Layout Documentation

> **Template.** Copy this to `docs/m2-s3-layout.md` and fill in.
> Commit alongside your branch by end of Lab 2.

---

## The shared bucket

**Name:** `accelya-airline-data-ap-south-1`
**Region:** `ap-south-1` (Mumbai)
**Date documented:** YYYY-MM-DD
**Documented by:** `<your-github-handle>` + `<pair-partner>`

---

## Zone layout

```
s3://accelya-airline-data-ap-south-1/
├─ raw/                  ← source-owned; cohort-shared synthetic data
│   ├─ AI/2026/05/...    ← per-airline synthetic test files (read-only)
│   ├─ BA/2026/05/...
│   ├─ EK/2026/05/...
│   └─ <your-name>/      ← YOUR write target — fires Lambda on Lab 3
│
├─ validated/<your-name>/    ← Lambda writes schema-passing rows here
│
├─ curated/<your-name>/      ← Day 6 writes Parquet here
│
├─ quarantine/<your-name>/   ← Lambda writes failed rows + sidecars
│
├─ learner-sandbox/<your-name>/    ← YOUR scratch space
│   └─ raw-staging/      ← Lab 2 staging area (NOT raw/!)
│
└─ models/               ← Day 9 model artefact (trainer-owned)
```

---

## Zone contracts

| Zone | Writer | Reader | Retention | Lifecycle |
|---|---|---|---|---|
| **raw/** | SFTP gateway (production); cohort-shared synthetic data (workshop) | Validator Lambda (read-only) | 7 years | Glacier after 90 days |
| **validated/** | Validator Lambda only | Curator Lambda (read-only) | 2 years | IA after 30 days |
| **curated/** | Curator Lambda only | Athena workgroup, dashboards | 5 years | IA after 90 days |
| **quarantine/** | Validator Lambda only | Ops console role | 30 days | Expire after 30 days |
| **learner-sandbox/\<learner\>/** | Owner only | Owner only | 30 days | Expire after 30 days |

---

## Object counts I observed (Lab 2 step 2)

```bash
aws s3 ls s3://accelya-airline-data-ap-south-1/raw/AI/ --recursive --summarize --region ap-south-1 | tail -2
```

| Airline | Objects | Total size |
|---|---|---|
| AI | <N> | <KB / MB> |
| BA | <N> | <KB / MB> |
| EK | <N> | <KB / MB> |
| LH | <N> | <KB / MB> |
| SQ | <N> | <KB / MB> |

---

## My staging upload (Lab 2 step 3)

**Source file:** `data/synthetic_ticket_issues.json` (500 records, 6 deliberate defects)
**Target:** `s3://accelya-airline-data-ap-south-1/learner-sandbox/<your-name>/raw-staging/2026/05/<date>/synthetic_ticket_issues.json`
**Why staging and NOT `raw/`:** uploading to `raw/<your-name>/` fires the Lab 3 Lambda prematurely. Lab 3's whole teaching point is the FIRST upload into `raw/<your-name>/`. Burning that early loses the live-trigger moment.

---

## Trigger boundary

```
s3://accelya-airline-data-ap-south-1/raw/<your-name>/  ← fires Lambda
s3://accelya-airline-data-ap-south-1/raw/AI/           ← does NOT fire (cohort-shared, not your prefix)
s3://accelya-airline-data-ap-south-1/learner-sandbox/<your-name>/  ← does NOT fire (different top-level)
s3://accelya-airline-data-ap-south-1/validated/<your-name>/  ← does NOT fire (different top-level)
```

The S3 → Lambda notification is scoped via `Filter.Key.FilterRules` to `prefix: raw/<learner>/`. This is what guards against same-bucket recursion: writes to `validated/` and `quarantine/` do not re-fire the Lambda.

---

## Format expectations per zone

| Zone | Format | Why |
|---|---|---|
| **raw/** | JSON arrays (whatever source provides) | Source-faithful; we don't transform on ingest |
| **validated/** | JSONL (one object per line) | Streams well downstream; Glue ETL (D6) reads line-by-line |
| **curated/** | Parquet (partitioned by source_system + ingest_date) | Columnar; Athena partition-prunes efficiently |
| **quarantine/** | JSON + sidecar JSON | Audit-grade evidence of failure |

---

## What I learned

(Optional — one or two sentences on something Lab 2 made click.)

- ...

---

*Source: Day 2 Lab 2 (deck slides 23-25). HITL Scalability + Cost dimensions: this is the evidence the bucket layout supports the intended workload.*
