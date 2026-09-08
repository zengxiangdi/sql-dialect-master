"""Regression tests for the stable exception error taxonomy."""

from backend.core.exceptions import (
    CacheError,
    ConfigurationError,
    ErrorCode,
    ParseError,
    RuleConflictError,
    SecurityViolationError,
    TranspileError,
    UnsupportedDialectError,
    ValidationError,
)


def test_exception_subclasses_expose_stable_error_codes() -> None:
    cases = [
        (UnsupportedDialectError("unknown", ["mysql"]), ErrorCode.UNSUPPORTED_DIALECT),
        (TranspileError("failed"), ErrorCode.TRANSPILE_FAILED),
        (ParseError("invalid"), ErrorCode.PARSE_FAILED),
        (SecurityViolationError("blocked"), ErrorCode.SECURITY_VIOLATION),
        (ValidationError("invalid", field="sql"), ErrorCode.VALIDATION_FAILED),
        (CacheError("cache failure"), ErrorCode.CACHE_FAILED),
        (ConfigurationError("bad config"), ErrorCode.CONFIGURATION_INVALID),
        (RuleConflictError("conflict", rule1="a", rule2="b"), ErrorCode.RULE_CONFLICT),
    ]

    for error, expected_code in cases:
        payload = error.to_dict()
        assert error.error_code == expected_code
        assert payload["error_code"] == expected_code.value
        assert payload["error_type"] == error.__class__.__name__
