# accelya-agentic-aws — Starter Repo

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

| Layer | Status | Edit? |
|---|---|---|
| `briefs/`, `docs/`, `glossary/`, `src/skeletons/` | **STATIC** | Read-only reference. Trainer-provided. |
| `prompts/`, `outputs/`, `reviews/` | **GREEN** | You commit here every module. Audit trail. |
| `HITL_REVIEW.md`, `.windsurfrules` | **YELLOW** | Update per module. These travel with your code. |

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

| Days | Modules | Theme |
|---|---|---|
| 1 | M1 | Foundation: setup + concepts |
| 2 | M2 | AWS fundamentals: IAM, S3, Lambda, CloudWatch |
| 3 | M3 | Agentic AI foundations for engineering teams |
| 4 | M4 | Batch pipeline design (on paper) |
| 5 | M5 | Agentic batch processing (implementation) |
| 6 | M6 | Data transformation, cataloguing & analytics (Glue + Parquet + Athena) |
| 7 | M7 | Streaming architecture |
| 8 | M8 | Agentic real-time processing (Kinesis consumer) |
| 9 | M9 | Real-time ML/DL inference (SageMaker Serverless) |
| 10 | M10 | Observability, security, cost |
| 11 | M11 | End-to-end integration with CI/CD |
| 12 | M12 | Capstone + expert review |

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

- **Post-course assessment**: <https://forms.cloud.microsoft/r/Nf1sdeqHKr>
- **Final feedback**: <https://forms.cloud.microsoft/r/Nx2Gpez5kc>

---

*Built for the Accelya Kale cohort, May–June 2026. Synthetic data only.*
