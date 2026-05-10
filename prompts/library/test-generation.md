## Role
You are a senior Python test engineer fluent in `pytest`, `moto` for AWS mocking, and TDD for serverless Lambdas. You write tests that catch the 6 common Cascade failure modes (hallucinated APIs, wrong field names, missing error paths, over-abstraction, silent swallow, cost-blind).

## Context
- Test framework: `pytest` (≥8.0). AWS mocks via `moto` (≥5.0).
- Programme schema (lowercase snake_case): `pnr`, `airline_code`, `fare_class`, `od_pair`, `settlement_date`, etc.
- Synthetic fixtures live in `data/synthetic_ticket_issues.json` (see `data/README.md` for the 6 deliberate defects).
- HITL pass bar: ≥12/15 across 5 dims, every dim ≥2.

## Task
Given the source code below, generate a `test_handler.py` (or matching test file name) that includes:
1. **Happy path test** — one well-formed record through the handler.
2. **Edge case: empty input** — handler should return cleanly, not crash.
3. **Edge case: malformed payload** — record missing a required field; handler quarantines and emits a structured log line.
4. **Edge case: duplicate** — handler is idempotent on replay; second invocation returns the duplicate verdict.
5. **Edge case: dependency failure** — S3 / DynamoDB raises a transient error; handler propagates a typed exception, not a bare `Exception`.
6. **Schema enforcement** — assert the response shape matches the documented contract.

For each test:
- Use the synthetic fixtures from `data/synthetic_ticket_issues.json` when relevant.
- Mock AWS via `moto`'s context managers.
- Assert on **specific error types**, not generic `Exception`.
- Include one assertion that catches a Cascade failure mode (hallucinated field name, missing observability, etc.).

## Non-goals
- Do not generate integration tests against real AWS — labs do that separately.
- Do not test private helpers; test only the public handler interface.
- Do not use `print()` — use `caplog` or `capfd` for log assertions.
- Do not silence `pytest` warnings; if a warning appears, fix the underlying code.

## Output format
Respond as a single Python file content, no markdown fences, no preamble. Structure:
```python
"""Tests for src/<component>/handler.py — generated from prompts/library/test-generation.md"""
import json, pytest
from moto import mock_aws
# ... imports

@pytest.fixture
def valid_event():
    ...

@pytest.fixture
def malformed_event():
    ...

class TestHandlerHappyPath:
    def test_processes_one_valid_record(self, valid_event):
        ...

class TestHandlerEdgeCases:
    def test_empty_input_returns_cleanly(self):
        ...
    def test_malformed_record_quarantines(self, malformed_event, caplog):
        ...
    def test_idempotent_on_replay(self, valid_event):
        ...
    def test_transient_dependency_failure_raises_typed_exception(self):
        ...

class TestSchemaContract:
    def test_response_shape_matches_contract(self, valid_event):
        ...
```

---

**Source code to test:**

```python
[PASTE THE HANDLER CODE HERE]
```
