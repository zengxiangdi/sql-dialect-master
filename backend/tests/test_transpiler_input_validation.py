"""Regression tests for core SQLTranspiler input validation."""

from backend.core.transpiler import SQLTranspiler


def test_transpile_rejects_non_string_sql_with_structured_error() -> None:
    result = SQLTranspiler().transpile(None, "mysql", "postgres")  # type: ignore[arg-type]

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert result.error == "sql must be a string"


def test_transpile_rejects_non_string_source_with_structured_error() -> None:
    result = SQLTranspiler().transpile("SELECT 1", None, "postgres")  # type: ignore[arg-type]

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert result.error == "source must be a string"


def test_transpile_rejects_non_string_target_with_structured_error() -> None:
    result = SQLTranspiler().transpile("SELECT 1", "mysql", None)  # type: ignore[arg-type]

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert result.error == "target must be a string"
