# Cascade Prompt Library

> This folder holds your prompts AND the trainer's reference prompt library.
> Every Cascade prompt that produces an artefact in this programme commits here.

## Naming convention

```
prompts/
├─ README.md                            # this file
├─ library/                             # trainer-provided reusable prompts
│   ├─ brd-drafting.md                  # turn a 1-line BR into a structured BRD
│   ├─ architecture-generation.md       # propose N architectures with scorecard
│   ├─ test-generation.md               # generate pytest tests from a handler
│   ├─ failure-mode-catalogue.md        # critique an artefact against the 6 failure modes
│   └─ refactor-for-hitl.md             # take Cascade output and lift it past 12/15
└─ m<N>-<purpose>-v<V>.md               # YOUR prompts per module, per version
```

Examples of your prompts:
- `prompts/m1-arch-v1.md` (Day 1 Lab 2 — first draft)
- `prompts/m1-arch-v2.md` (refinement after first scoring)
- `prompts/m3-validator-v1.md` (Day 3 Lab 3 weak validator prompt)
- `prompts/m3-validator-v2.md` (Day 3 Lab 3 strong validator prompt — closes 6 failure modes)

## Why we commit prompts

1. **Audit trail** — every artefact has a prompt that produced it. Reviewers in Module 12 read back the iteration history.
2. **Learning artefact** — the v1 → v2 → vN progression IS the lesson. You learn by seeing what you had to add.
3. **Cohort reuse** — your peers can adapt your prompts. The starter `library/` is the seed.

## Conventions

- **Plain Markdown**, no front-matter, no YAML.
- **5 sections** in order: `## Role`, `## Context`, `## Task`, `## Non-goals`, `## Output format`. See `docs/prompt-template.md`.
- **Use airline vocabulary** (`pnr`, `od_pair`, `settlement_date`). Generic names (`order`, `user`) fail review.
- **Pair with `outputs/`** — the raw Bedrock response goes to `outputs/m<N>-<purpose>-output.json`.
- **Pair with `reviews/`** — the HITL scorecard goes to `reviews/HITL_REVIEW-<artefact>.md`.

---

*See `prompts/library/` for the trainer-provided reusable prompts (BRD drafting, architecture generation, test generation, failure-mode critique, refactor-for-HITL).*
