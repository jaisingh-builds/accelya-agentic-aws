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
]


class PipelineError(Exception):
    """Base class for every typed error raised by programme code."""

    quarantine_reason: str = "pipeline_error"   # subclasses override


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
