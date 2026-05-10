# src/ — Source Code

Module-by-module Lambda code grows in here.

## Layout

```
src/
├─ common/           # shared types and helpers (cross-module)
│   ├─ __init__.py
│   ├─ exceptions.py   # PipelineError ladder
│   └─ logging.py      # powertools Logger setup (Module 4+)
│
├─ validator/         # Module 5 — first real Lambda
│   ├─ __init__.py
│   ├─ handler.py
│   └─ test_handler.py
│
├─ chunker/           # Module 5 — splits files into S3 chunks
├─ lander/            # Module 5 — aggregates Map output, writes manifest
├─ dlq_replayer/      # Module 5 — DLQ classifier + replay
│
├─ producer/          # Module 7 — Kinesis producer
├─ consumer/          # Module 8 — Kinesis consumer with RBIF
├─ predict/           # Module 9 — SageMaker Serverless wrapper
├─ bedrock_enrich/    # Module 8 — Bedrock-side enrichment
└─ ... etc
```

## Conventions

- One folder per Lambda. **Don't put two handlers in one folder.**
- Each handler folder has: `__init__.py`, `handler.py`, `test_handler.py`.
- Shared types in `src/common/`. Import from there.
- **No bare `except: pass`.** Use the `PipelineError` ladder.
- **No `Action:*` / `Resource:*` in any IAM** referenced from code or template.
- Logging via `aws_lambda_powertools.Logger` with `correlation_id` (Module 4+).
- Tests live next to the handler: `src/validator/test_handler.py`.

## How modules add to this

- **Module 1 / 2**: src/ is mostly empty. The cohort doesn't ship src/ code yet.
- **Module 3**: src/weak_validator/ + src/strong_validator/ (the weak-vs-strong critique lab).
- **Module 4**: design only, no new src/.
- **Module 5**: src/chunker/, src/validator/, src/lander/, src/dlq_replayer/.
- **Module 6**: src/etl_to_parquet/ (single Glue ETL Lambda).
- **Module 7–9**: streaming + inference Lambdas.
- **Module 10**: src/obs_wrapper/ (cross-cutting observability decorator).
- **Module 11**: end-to-end stitch; no new Lambdas (re-uses earlier).
- **Module 12**: capstone — fresh src/ folder for the integrative artefact.

By Module 12 you'll have ~10 Lambdas under src/. The sandbox cap is 10; that's not coincidence — the programme is calibrated to fill the cap exactly.
