# 5-Section Prompt Template

> The anatomy. Day 1 Concept 6 + Lab 2. Used for every Cascade / Bedrock prompt in the programme.
> Order matters. The discipline of writing each section is half the work.

---

## Template

```markdown
## Role
[One sentence. What kind of expert is the model?]

## Context
[Business setting + constraints + airline vocabulary.
Use specific terms from glossary/airline.md.]

## Task
[What to produce. Be unambiguous. One verb + one deliverable per task line.]

## Non-goals
[What NOT to include. Prevents over-engineering.
List the services/patterns Cascade tends to over-propose for this task.]

## Output format
[Specify exact structure for parsing + review.
For JSON: schema with field names and types.]
```

---

## Worked example (Day 1 Lab 2 — `prompts/m1-arch-v1.md`)

```markdown
## Role
You are a senior AWS data architect specialising in airline batch pipelines.

## Context
Accelya processes daily ticket-issue files (CSV, ~50MB) per airline.
Required fields: pnr, airline_code, fare_class, od_pair, settlement_date.
Files arrive at S3 raw zone via SFTP gateway. Region: ap-south-1.
Sandbox caps: 10 Lambdas, 3 Glue jobs, 4 DPU total, 50 Bedrock invocations.

## Task
Propose two architectures for ingesting and validating these files.
Compare them on cost, latency, and reviewability.

## Non-goals
Do not propose Glue Streaming, Step Functions, or any GCP/Azure service.
No multi-region designs.

## Output format
Respond as JSON array of two objects, each with keys:
  option_name (string), services (list of strings), data_flow (string),
  trade_offs (string), estimated_monthly_cost (illustrative only —
  actual pricing will be validated later using AWS pricing / metrics).
```

---

## Section-by-section discipline

### 1. Role

- **Name the seniority + specialisation.** "Senior AWS data architect" is better than "expert" because Cascade weights AWS-specific knowledge higher.
- **One sentence, max two.** If you need three, you're putting Context in Role.
- Examples that work:
  - "You are a senior AWS data architect specialising in airline batch pipelines."
  - "You are a backend engineer fluent in Python, boto3, and Lambda best practices."
  - "You are a SOC2-aware security reviewer with experience in IAM least-privilege patterns."

### 2. Context

- **State the business setting first.** "Accelya processes daily ticket-issue files..." — this primes airline vocabulary.
- **List required fields by exact name.** Use the schema from `glossary/airline.md`. Generic field names hallucinate.
- **Specify infrastructure constraints.** Region, sandbox caps from `.windsurfrules`, prior-module artefacts the model should respect.
- **Don't paste the full BR; summarise.** The BR lives in `briefs/m<n>.md`. The prompt summarises the BR with the constraints baked in.

### 3. Task

- **One imperative verb.** "Propose", "Implement", "Refactor", "Score", "Critique".
- **One deliverable.** Two architectures, one Lambda handler, one ASL state machine.
- **Specify comparison axes** if the task has multiple options. "Compare on cost, latency, reviewability" focuses the model's trade-offs.

### 4. Non-goals

- **The cheapest prompt improvement.** Cascade over-proposes by default; Non-goals cuts it back.
- **List the services + patterns** you've seen Cascade gravitate toward for this task. For "design a batch pipeline" it tends to over-reach into Glue Streaming, Step Functions, multi-region. Ban those.
- **Module-specific Non-goals migrate to `.windsurfrules`** if you find yourself repeating them. Anything in `.windsurfrules` doesn't need to be in every prompt.

### 5. Output format

- **JSON > prose** for anything that gets parsed downstream.
- **Specify the schema.** Field names, types, nesting. "Respond as JSON" alone produces free-form JSON with arbitrary keys.
- **Add "no markdown fences"** if you've seen Cascade wrap JSON in ```json blocks.
- **Add "no preamble"** if you've seen Cascade say "Here is the JSON:" before the JSON.

---

## When to refine vs when to ship

| Symptom | Fix |
|---|---|
| Cascade ignores Non-goals | Restate in Task: *"Task: ... Do NOT include X under any circumstances."* |
| JSON output has wrong field names | Specify schema in Output format more explicitly. |
| Cascade keeps making the same mistake | Move the constraint to `.windsurfrules` — it's persistent. |
| Output is too long | Add to Output format: *"Each option max 150 words."* |
| Output is too short | Add to Task: *"Include data_flow with explicit S3 zones and IAM boundaries."* |
| Generic field names (`order`, `user`) | The `glossary/airline.md` reference isn't being read — paste the field list directly into Context. |

---

## Prompt versioning

- First draft: `prompts/m<n>-<purpose>-v1.md`
- Refinement after first run: `prompts/m<n>-<purpose>-v2.md` — DO commit v1 too.
- Final version that produced the artefact you shipped: highest `v<N>`.

The progression v1 → v2 → vN is the audit trail. Reviewers in Module 12 can read the iteration and see what you learned.

---

## Anti-patterns

1. **Single huge prompt** — split into multiple smaller prompts if the model is over-summarising.
2. **No Output format** — get the model talking in your shape from word one.
3. **Vague Role** — "you are an AI assistant" is no role at all.
4. **Missing Non-goals** — you'll get an answer; it just won't be the answer you want.
5. **Pasting real customer data in Context** — see `docs/data-safety.md`. Synthetic only.

---

*Living document. Update with patterns the cohort discovers. Commit changes to `docs/prompt-template.md` with a one-line changelog at the top.*
