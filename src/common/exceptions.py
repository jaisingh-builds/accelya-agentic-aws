"""
src/common/exceptions.py — programme PipelineError ladder.

Every Lambda in the programme raises one of these (or a subclass).
Bare `Exception` and `except: pass` are banned (HITL Observability = 0).

This ladder is consumed by:
- The ASL state machine Catch clauses (Day 5+) — each named error routes to a Quarantine* state.
- The structured JSON logger — `error_type` field is the class name.
- The DLQ classifier (Day 5 Lab 3) — re-drive vs quarantine vs escalate decisions.

Subclass tree:

    PipelineError                       base
      ├─ ValidationError                schema / required fields / type
      │   ├─ SchemaError                missing required field
      │   ├─ ReferenceError             invalid IATA code / unknown airline
      │   └─ TypeMismatchError          string in numeric field, etc.
      ├─ BusinessRuleError              record violates a business rule
      │   ├─ DateOutOfRangeError        e.g. future-dated settlement
      │   └─ DuplicateError             idempotency catches a replay
      ├─ TransientError                 retry-eligible failures
      │   ├─ ThrottledError             AWS throttling
      │   └─ DependencyTimeoutError     S3/DynamoDB/Bedrock timeout
      ├─ ConfigError                    static config problem
      │   ├─ MissingEnvVarError         env var not set
      │   └─ MalformedRowError          input file unparseable
      └─ MalformedRowError              (alias above)

Authors: in Module 4+, add new subclasses as the domain requires.
Never use bare `Exception`.
"""

__all__ = [
    "PipelineError",
    "ValidationError",
    "SchemaError",
    "ReferenceError",
    "TypeMismatchError",
    "BusinessRuleError",
    "DateOutOfRangeError",
    "DuplicateError",
    "TransientError",
    "ThrottledError",
    "DependencyTimeoutError",
    "ConfigError",
    "MissingEnvVarError",
    "MalformedRowError",
    "ManifestMismatchError",
    "SchemaInferenceError",
]


class PipelineError(Exception):
    """Base class for every typed error raised by programme code.

    Carries structured context so ASL Catch handlers + DLQ replayer can
    classify without parsing the message string.

    Day 5+ handlers raise with kwargs:
        raise SchemaError("missing fare_amount", file_key=..., line_no=...)

    Day 2-4 callers that pass only a positional message still work because
    every kwarg is optional and defaults to None.
    """

    quarantine_reason: str = "pipeline_error"   # subclasses override

    def __init__(
        self,
        message: str = "",
        *,
        file_key: str | None = None,
        line_no: int | None = None,
        chunk_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.file_key = file_key
        self.line_no = line_no
        self.chunk_id = chunk_id
        self.detail = detail


# ── Validation ────────────────────────────────────────────────────────────
class ValidationError(PipelineError):
    quarantine_reason = "validation"


class SchemaError(ValidationError):
    """Required field missing, or schema-drift detected."""
    quarantine_reason = "schema_drift"


class ReferenceError(ValidationError):  # noqa: A001 — shadows builtin intentionally
    """Field value not in the allowed reference set (e.g. invalid IATA code)."""
    quarantine_reason = "reference_drift"


class TypeMismatchError(ValidationError):
    """Field present but wrong type (e.g. string in numeric)."""
    quarantine_reason = "type_error"


# ── Business rules ────────────────────────────────────────────────────────
class BusinessRuleError(PipelineError):
    quarantine_reason = "business_rule"


class DateOutOfRangeError(BusinessRuleError):
    """e.g. future-dated settlement_date."""
    quarantine_reason = "business_rule"


class DuplicateError(BusinessRuleError):
    """Idempotency catches a replay. Not raised — logged + skipped silently."""
    quarantine_reason = "duplicate"


# ── Transient (retry-eligible) ────────────────────────────────────────────
class TransientError(PipelineError):
    """Retry-eligible (Step Functions Catch with Retry policy)."""
    quarantine_reason = "transient"


class ThrottledError(TransientError):
    pass


class DependencyTimeoutError(TransientError):
    pass


# ── Config (static) ───────────────────────────────────────────────────────
class ConfigError(PipelineError):
    quarantine_reason = "config"


class MissingEnvVarError(ConfigError):
    pass


class MalformedRowError(ConfigError):
    """Input file unparseable (not JSON, not valid CSV)."""
    quarantine_reason = "malformed"


# ── Manifest mismatch (Day 5 — lander) ────────────────────────────────────
class ManifestMismatchError(PipelineError):
    """Lander manifest row_count != aggregated validated+quarantined+duplicate.

    Raised by `src/lander/handler.py` when chunk-level results don't reconcile
    to the chunker's reported `row_count`. ASL Catch routes to QuarantinePartial.
    """
    quarantine_reason = "partial"


# ── Schema inference conflict (Day 6 — ETL Lambda / Crawler) ──────────────
class SchemaInferenceError(PipelineError):
    """Crawler or ETL discovers conflicting types across files.

    Examples:
      - File A has `fare_amount` as DOUBLE; File B has it as STRING.
      - Crawler infers different partition column types across runs.
      - ETL receives an input row with a type that PyArrow `table.cast(SCHEMA)`
        cannot coerce (e.g. non-numeric in DECIMAL column).

    ASL Catch (when wired in Day 11) routes to QuarantineSchemaDrift.
    """
    quarantine_reason = "schema_drift"
