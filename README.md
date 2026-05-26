# accelya-agentic-aws — Starter Repo

> **Programme Lead & Trainer — Jai Singh**
> Fractional CTO · Enterprise AI Advisor · Corporate Trainer
> 📧 [jaisingh.cto@gmail.com](mailto:jaisingh.cto@gmail.com) · 📱 [+91 99718 71006](tel:+919971871006) · 💼 [LinkedIn](https://www.linkedin.com/in/jai-singh-cto/) · 💻 [GitHub](https://github.com/jaisingh-builds)
>
> *Available for: agentic-AI architecture reviews, enterprise rollout strategy, executive coaching, and follow-on cohort delivery. Reach out on any channel — fastest response on WhatsApp.*

---

## ⭐ Career & Learning Map — Agentic AI for Senior Devs & Solution Architects

**The shift:** Q1 2026 agentic-AI job postings grew 280% YoY. Every senior cloud / SA role now expects agent design skills. India market pays a 1.5×–2.5× premium over traditional cloud-SA roles for this combination:

- **Senior AI Solutions Architect (8+ yrs)** — avg ₹42 LPA nationally; Bangalore ₹38–55 LPA (14% above national avg)
- **Agentic-AI specialists, mid-senior** — ₹35–80 LPA in mainstream enterprises
- **Top-decile (Bengaluru / Gurugram, FAANG + top AI startups)** — ₹80 L–₹2 Cr+ TC
- **Independent / fractional consulting day rate** — ₹40k–₹2 L/day for senior agentic-AI architects

**This 12-day programme gave you the foundation.** Use the map below to compound it into a career move.

### Step 1 — Pick your lane (week 1)


| Lane                               | Best for                                              | Stack you double down on                            |
| ---------------------------------- | ----------------------------------------------------- | --------------------------------------------------- |
| **Agent-Ops Architect**            | SAs who liked Day 9–10 (eval, drift, HITL)            | Step Functions + CloudWatch + custom eval harnesses |
| **MCP / Integration Architect**    | SAs who own enterprise SaaS surfaces                  | MCP servers, A2A protocols, tool-calling contracts  |
| **AI Risk + Compliance Architect** | SAs who deal with legal / audit / regulated workloads | EU AI Act, model cards, audit trails, HITL design   |
| **Domain-Vertical Architect**      | SAs deep in airline / claims / supply chain           | Your domain + this stack — hardest to replace       |


### Step 2 — Ship one production-grade agent (days 1–30)

Pick a real internal workflow (intake routing, refund triage, ops ticket). Build using the stack from this programme: **SAM + Bedrock + Step Functions + CodeDeploy auto-rollback + PreTraffic hook**. End the month with a green PR + integration test. This is your portfolio piece, not a tutorial repo.

### Step 3 — Make it agentic + auditable (days 31–60)

Add MCP tool-calling. Add the confidence-threshold → SQS review pattern from Day 10. Build an eval harness that measures drift, hallucination, and escalation rate. Produce a one-page architecture doc and a cost-per-1000-runs number.

### Step 4 — Lead an org-level decision (days 61–90)

Write an ADR: "when does my company use an agent vs. a Lambda?" Map 3 internal workflows on a build/buy/wait grid. Run a multi-team design review. The artifact is the ADR + decision grid — that's senior-architect signal.

### Step 5 — Courses & certifications (in priority order)

1. **[DeepLearning.AI — Agentic AI** (Andrew Ng)](https://www.deeplearning.ai/) — vendor-neutral 4-pattern foundation in raw Python. Do this first.
2. **[Anthropic Claude API + Agent SDK docs](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview)** — free, the most current source of truth for what you just used.
3. **[Microsoft Agentic AI Business Solutions Architect (AB-100)](https://learn.microsoft.com/en-us/credentials/certifications/agentic-ai-business-solutions-architect/)** — the credential most hiring managers will actually recognize in 2026.
4. **[AWS Certified Generative AI Developer Professional](https://aws.amazon.com/certification/)** — covers Bedrock Agents, complements what you built here.
5. **[IBM RAG & Agentic AI Professional Certificate** (Coursera, ~3 months)](https://www.coursera.org/professional-certificates/ibm-rag-and-agentic-ai) — strong RAG fundamentals if you're light there.
6. **[NVIDIA Agentic AI Professional Certification](https://www.nvidia.com/en-us/learn/certification/)** — useful if you go toward inference-heavy / on-prem workloads.

**Skip:** generic "AI Engineer" bootcamps, anything that only teaches LangChain syntax without ops + eval + rollback.

### What's commoditizing vs compounding (read before choosing)

- **Commoditizing:** writing CFN from a spec, boilerplate IAM, CRUD APIs, single-cloud reference architectures, certs taken in isolation.
- **Compounding:** judgment under ambiguity, HITL + reversibility design, cost modeling for non-deterministic systems, stakeholder translation (legal/risk/ops), operating live agents, MCP / A2A integration shape.

**Calculator analogy:** arithmetic got cheap, mathematicians got more valuable. Your trade-offs and ops judgment are the part that pays.

---

## 📝 Post-Course Assessment — Answer Key

Source: *Agentic Development using AWS — Post Test — Accelya Solutions India Ltd (WO: C/2026/59)*. 20 graded MCQs, 1 point each. (The MS Form prepends two info fields — Name + Employee Code — before the graded section; those are omitted here. Numbering below is the graded sequence Q1–Q20.)

**Q1. S3 → Lambda integration for 15-min ticket-issue uploads.**
✅ **A. Configure an S3 Event Notification on the bucket (s3:ObjectCreated:*, prefix raw/ticket-issue/) with the Lambda as destination.**
*Why:* native push integration — Lambda fires the moment the object lands, no polling cost, no scheduling lag. Cheapest and most direct of the four.

**Q2. Least-privilege IAM for read-from-raw, write-to-validated.**
✅ **C. Grant s3:GetObject on arn:aws:s3:::accelya-lab-data/raw/ticket-issue/\* and s3:PutObject on arn:aws:s3:::accelya-lab-data/validated/ticket-issue/\* only.**
*Why:* IAM resource-level scoping uses object ARNs, not the bucket ARN. The bucket-ARN-only option (D) doesn't constrain prefixes; managed FullAccess (A) and s3:* (B) violate least-privilege.

**Q3. CloudWatch Logs Insights — count records per airline_code per hour.**
✅ **B. Emit structured JSON log lines that include fields such as airline_code, pnr, ticket_number, event_type, and correlation_id.**
*Why:* Logs Insights parses JSON fields automatically — you can `stats count() by airline_code, bin(1h)`. Plain-text strings require regex parsing on every query.

**Q4. Cost-efficient analytics layout on S3 for Athena settlement reconciliation.**
✅ **C. Store as Parquet, partitioned by settlement_date and airline_code, and register the table in the Glue Data Catalog with explicit schema.**
*Why:* columnar + partition pruning + explicit schema = minimal scan cost. CSV/JSON Lines hurt scan economics; unpartitioned Parquet still reads the whole dataset.

**Q5. Role of the Glue Data Catalog for a curated S3 dataset.**
✅ **B. It registers the dataset's database, table, schema, and partitions as metadata so Athena (and other engines) can query the S3 data with partition pruning.**
*Why:* Glue Catalog is a metadata store — it doesn't hold data (A), isn't a metrics store (C), and doesn't enforce IAM on S3 (D).

**Q6. Streaming (near real-time) vs batch — strongest case.**
✅ **C. Evaluating cancellation requests the moment they arrive to classify them against fare rules and route them to refund processing.**
*Why:* per-event latency matters; the business action (refund routing) is time-sensitive. Daily reports, back-fill, and weekly training are batch-friendly.

**Q7. Fare class, fare rules, and refund behaviour.**
✅ **B. A ticket's fare class determines the applicable cancellation and refund rules, which in turn drive the refund calculation (Saver = penalty, Flex = often fully refundable).**
*Why:* fare class is set at issuance and is the input to fare-rule lookup, which yields refund behaviour.

**Q8. Human-in-the-Loop (HITL) in an agentic engineering workflow.**
✅ **A. A human engineer reviews AI-generated architecture options, code, or tests against explicit review criteria (correctness, IAM, observability, scalability, cost) before the artefact is accepted.**
*Why:* HITL is a structured review gate against criteria — not the AI self-evaluating (D), not a CI silently rejecting code (C), and certainly not the engineer typing while AI watches (B).

**Q9. Best prompt for an Azure OpenAI-drafted Lambda validator.**
✅ **C. The senior-engineer role prompt with explicit field list, reject-on-rule, folder layout (handler/service/validator/config/tests), structured JSON logs with correlation_id, three failure-case unit tests, no external network calls.**
*Why:* specificity + role + acceptance criteria + non-functional constraints = reviewable first draft. Vague prompts (A, B) and "ship to prod" (D) produce unreviewable code.

**Q10. CloudWatch alarm for a quarantine-rate spike.**
✅ **B. Emit a custom CloudWatch metric (e.g. QuarantinedRecords) from the Lambda on every rejection, and alarm when its rate over a 5-minute window exceeds a tuned baseline.**
*Why:* a domain-specific metric tells you *what* is wrong. Invocations (A) doesn't distinguish good vs bad records; EC2 CPU (C) is the wrong scope; WARN-on-everything (D) is alarm fatigue.

**Q11. Kinesis hot-shard — 90% of traffic on one shard.**
✅ **B. Cause: partition key is airline_code, concentrating the dominant airline's traffic onto a single shard. Fix: choose a higher-cardinality partition key like pnr (or composite airline_code#pnr).**
*Why:* this is the textbook Kinesis hot-shard pattern. Reducing shards (A) makes it worse; Lambda vs SQS (C) and S3 events (D) don't address the partitioning root cause.

**Q12. Idempotency under Kinesis at-least-once delivery.**
✅ **B. Use a DynamoDB "dedupe" table keyed on a stable business identifier (e.g. (ticket_id, cancellation_timestamp)) with a conditional write, so a second attempt is rejected at the storage layer.**
*Why:* idempotency requires a persistent, atomic check on a deterministic key. Longer timeouts (A), longer retention (C), and provisioned concurrency (D) don't make processing safe under duplicates.

**Q13. Failure handling for a Kinesis-triggered Lambda.**
✅ **A. Configure the Lambda event source mapping with a DLQ / on-failure destination (SQS or SNS), combined with appropriate MaximumRetryAttempts and MaximumRecordAgeInSeconds, to prevent a poison record from blocking the shard.**
*Why:* without bounded retry + DLQ, a poison record blocks the shard indefinitely (Kinesis preserves order per shard). Options B/C/D are factually wrong.

**Q14. Athena query pattern that minimises scan cost on partitioned Parquet.**
✅ **B. SELECT t.\* FROM curated.ticket_issue t WHERE t.settlement_date = DATE '2026-04-17' AND t.airline_code = 'AI' AND <remittance-match predicate>; Athena prunes partitions to a single slice and reads only the relevant Parquet files.**
*Why:* partition pruning happens only when the WHERE clause filters on partition columns. `SELECT *` then client-filter (A) reads everything; LIKE on a non-partition column (C) defeats pruning; Parquet→CSV UDF (D) is absurd.

**Q15. SageMaker Serverless Inference cold-start mitigation.**
✅ **B. Serverless Inference can experience cold starts after idle periods; mitigations: tune max concurrency, use Provisioned Concurrency if traffic is predictable, document a fallback (e.g. manual-review queue) on timeout inside the Lambda.**
*Why:* the standard architectural answer to "p99 spikes after idle." Serverless isn't inappropriate (A), cold starts are tied to memory + model size (so C is wrong), and Lambda layers don't host SageMaker models (D).

**Q16. Strongest least-privilege IAM in the sandbox.**
✅ **B. s3:GetObject scoped to raw/ticket-issue/\*, s3:PutObject scoped to validated/ticket-issue/\*, condition aws:ResourceAccount = sandbox account, kms:Decrypt restricted to the specific CMK ARN.**
*Why:* prefix-scoped resource ARNs + account condition + key-scoped KMS = layered least-privilege. PowerUserAccess (C) is the opposite; NotResource:"*" (D) is broken policy syntax.

**Q17. Kinesis ESM with BatchSize=10, MaxBatchingWindow=5s — trade-off.**
✅ **B. It trades per-event latency against throughput and cost: Lambda waits up to 5s (or until 10 records) before invoking — reduces invocation count and cost but can add up to 5s latency for low-traffic shards.**
*Why:* batching is a latency-vs-cost knob; it has nothing to do with delivery semantics (A), DLQ behaviour (C), or single-threading (D).

**Q18. Reconciliation join producing false positives on fare-class changes.**
✅ **C. Model the ticket as slowly changing (e.g. fare-class history with valid-from / valid-to timestamps) and reconcile using the fare class that was active at the remittance event's timestamp.**
*Why:* this is a classic SCD Type 2 problem — joins on point-in-time attributes against event-time. Widening the predicate (B) papers over the bug; timeout (A) and Parquet→CSV (D) miss the point.

**Q19. Copilot-generated code review — three issues.**
✅ **B. Issues (1) and (2) are real anti-patterns (silent-except hides operational failures; hardcoded names break config-driven environments) and (3) is an AI hallucination — s3:putObject is not a valid IAM action; it must be s3:PutObject. The PR should be rejected and corrected.**
*Why:* IAM action names are case-sensitive. Silent except + hardcoded values are red flags every senior reviewer must catch.

**Q20. Cohort-scale HITL recommendation — direct-consumer vs orchestrator.**
✅ **B. Pattern (i) — for current scale it has fewer moving parts, lower cost, simpler observability, and still supports DLQ and idempotency. Pattern (ii) is appropriate to revisit when per-stage scaling, backpressure, or independent deployment become real concerns.**
*Why:* "more components = better architecture" is a fallacy. Defensible HITL = choose the simplest architecture that meets requirements; complexity-by-design is anti-pattern.

> **Scoring guide:** 18+/20 = strong; 14–17 = solid; 10–13 = revisit the relevant module(s); <10 = re-do the labs end-to-end. Pair every wrong answer with the module artefact (lab guide + study guide) that covers that concept.

---

Starter repo for the **Agentic Development using AWS for Airline Data Pipelines & Real-Time Inference** programme. 12 half-day modules over 12 days.

## What this repo is

The single source of truth for every artefact you produce in this programme:

- Your **prompts** (the audit trail).
- The **outputs** Bedrock returned.
- Your **HITL scorecard reviews**.
- The **source code** (from Module 4 onward).
- **Infrastructure-as-code** (SAM templates).
- **Tests** (unit + functional).

Branch per module per learner: `module-<n>-<your-name>`.

## Folder layout

```
accelya-agentic-aws/
├─ briefs/        # 1-line business requirements per module (trainer-provided)
├─ docs/          # templates, guides, HITL_REVIEW template
├─ glossary/      # airline vocabulary (PNR, OD, fare class, settlement...)
├─ prompts/       # YOUR prompts — the audit trail. Commit every prompt.
├─ outputs/       # raw model responses (JSON)
├─ reviews/       # HITL scorecards (CSV + filled HITL_REVIEW.md per artefact)
├─ src/           # source code (handlers, validators) — Module 4+
├─ scripts/       # verify_bedrock.py, cleanup scripts
├─ infra/         # SAM templates (Module 11+)
├─ tests/         # unit + functional tests
├─ data/          # synthetic data pack (DO NOT commit real data, ever)
├─ HITL_REVIEW.md # the running per-module checklist
├─ .windsurfrules # Cascade context — read on every prompt
└─ README.md
```


| Layer                                             | Status     | Edit?                                           |
| ------------------------------------------------- | ---------- | ----------------------------------------------- |
| `briefs/`, `docs/`, `glossary/`, `src/skeletons/` | **STATIC** | Read-only reference. Trainer-provided.          |
| `prompts/`, `outputs/`, `reviews/`                | **GREEN**  | You commit here every module. Audit trail.      |
| `HITL_REVIEW.md`, `.windsurfrules`                | **YELLOW** | Update per module. These travel with your code. |


## Day 1 first steps

```bash
# 1. Clone (use your branch when you make commits)
git clone https://github.com/jaisingh-builds/accelya-agentic-aws.git
cd accelya-agentic-aws

# 2. Make your branch
git checkout -b module-1-<your-name>

# 3. Install deps
python3 -m pip install -U boto3

# 4. Verify Bedrock works
export AWS_DEFAULT_REGION=ap-south-1
python3 scripts/verify_bedrock.py
# Expect: ✅ Bedrock Converse OK + token counts + model reply

# 5. Open in Windsurf
windsurf .
# Cascade should pick up .windsurfrules on every prompt (Lab 1 verifies)
```

## The non-negotiables (read these before you do anything)

1. **Synthetic data only.** No real Accelya customer or production data. Ever. See `docs/data-safety.md`.
2. **Prompts commit to GitHub** as audit artefacts. Treat them like code review comments.
3. **5-dim HITL scoring** (Correctness · Security · Observability · Scalability · Cost). Each 0–3. **PASS = ≥12/15 AND every dim ≥2.**
4. **One region: `ap-south-1`** (Mumbai).
5. **Bedrock model: `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`** (APAC cross-region inference profile). Trainer may override per cohort.

## Programme structure


| Days | Modules | Theme                                                                  |
| ---- | ------- | ---------------------------------------------------------------------- |
| 1    | M1      | Foundation: setup + concepts                                           |
| 2    | M2      | AWS fundamentals: IAM, S3, Lambda, CloudWatch                          |
| 3    | M3      | Agentic AI foundations for engineering teams                           |
| 4    | M4      | Batch pipeline design (on paper)                                       |
| 5    | M5      | Agentic batch processing (implementation)                              |
| 6    | M6      | Data transformation, cataloguing & analytics (Glue + Parquet + Athena) |
| 7    | M7      | Streaming architecture                                                 |
| 8    | M8      | Agentic real-time processing (Kinesis consumer)                        |
| 9    | M9      | Real-time ML/DL inference (SageMaker Serverless)                       |
| 10   | M10     | Observability, security, cost                                          |
| 11   | M11     | End-to-end integration with CI/CD                                      |
| 12   | M12     | Capstone + expert review                                               |


## Programme conventions (locked Day 1)

- **HITL scoring**: 0–3 per dim, 5 dims, max 15. PASS ≥ 12/15 AND every dim ≥ 2.
- **.windsurfrules sections** (v1): REPO RULES · CONSTRAINTS · EXAMPLES · REVIEW. v2 adds two batch blocks (Day 5). v3 adds CATALOG CONTEXT (Day 6). v7 adds OBSERVABILITY (Day 10).
- **Programme schema** (locked from Day 4): `pnr`, `airline_code`, `fare_class`, `od_pair`, `settlement_date` — lowercase snake_case.
- **Region**: `ap-south-1`.
- **Cleanup discipline**: every module ends with `scripts/cleanup_module<n>.sh`. Branch + MR open before you leave.

## Support

- **Trainer**: Jai Singh — see programme contact list in your invite.
- **Programme reference docs**: `docs/programme-content-plan.md`, `docs/sandbox-rules.md`, `docs/toolchain-vocab.md`.
- **Day-by-day handouts**: distributed at the start of each module.

## Course completion

- **Post-course assessment**: [https://forms.cloud.microsoft/r/Nf1sdeqHKr](https://forms.cloud.microsoft/r/Nf1sdeqHKr)
- **Final feedback**: [https://forms.cloud.microsoft/r/Nx2Gpez5kc](https://forms.cloud.microsoft/r/Nx2Gpez5kc)

---

*Built for the Accelya Kale cohort, May–June 2026. Synthetic data only.*