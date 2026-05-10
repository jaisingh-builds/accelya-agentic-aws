# HITL_REVIEW — <artefact-name>

> **Template.** Copy to `reviews/HITL_REVIEW-<artefact-name>.md` in your branch for each artefact.

---

**Artefact:** `<path/to/file>` (e.g. `src/strong_validator/handler.py`)
**Reviewer:** `<your-github-handle>`
**Date:** YYYY-MM-DD
**Module:** `<M1 ... M12>`
**Lab:** `<lab-N>`

---

## The score (0–3 per dim · PASS = ≥12/15 AND every dim ≥2)

| Dim            | Score | Evidence (one line per dim)                          |
|----------------|-------|------------------------------------------------------|
| Correctness    |       |                                                      |
| Security       |       |                                                      |
| Observability  |       |                                                      |
| Scalability    |       |                                                      |
| Cost           |       |                                                      |
| **TOTAL**      | __/15 |                                                      |

**Verdict:** PASS / REVISE

---

## Per-dimension detail

### Correctness — `<score>/3`

**Anchors:**
- **3** — matches spec + edge cases tested
- **2** — matches spec; happy path only
- **1** — matches spec but missing field or wrong API name
- **0** — doesn't compile / hallucinated APIs

**Evidence:** `<bullet ≥1 specific observation>`

---

### Security — `<score>/3`

**Anchors:**
- **3** — ARN-scoped IAM + named verbs + Conditions; secrets via env; PII tagged
- **2** — no wildcards; secrets via env; PII not addressed
- **1** — some wildcards present
- **0** — `Action: "*"` / `Resource: "*"` / hardcoded secrets

**Evidence:** `<bullet>`

---

### Observability — `<score>/3`

**Anchors:**
- **3** — powertools Logger + correlation_id + EMF + classified errors
- **2** — JSON logs + classified errors; no metrics yet
- **1** — JSON logs only
- **0** — `print` statements / silent `except: pass`

**Evidence:** `<bullet>`

---

### Scalability — `<score>/3`

**Anchors:**
- **3** — idempotent + bounded memory + maintainable + tested at 10× scale
- **2** — idempotent + bounded; maintainability OK
- **1** — idempotent only
- **0** — unbounded memory, non-idempotent, OR over-abstracted

**Evidence:** `<bullet>`

---

### Cost — `<score>/3`

**Anchors:**
- **3** — workload-appropriate service + sampled where applicable + cost-per-record measurable
- **2** — workload-appropriate service; no sampling discipline
- **1** — workload-appropriate; cost not considered
- **0** — wrong service for the workload

**Evidence:** `<bullet>`

---

## If REVISE: what to change

1. **<Dim>** — `<concrete change request>`
2. **<Dim>** — `<concrete change request>`

**Next iteration prompt addition:** `<text to append to the prompt>`

---

*Pass bar: ≥12/15 AND every dim ≥2.*
