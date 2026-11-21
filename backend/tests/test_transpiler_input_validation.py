"""Regression tests for core SQLTranspiler input validation."""

from typing import cast

from backend.core.transpiler import SQLTranspiler


def test_transpile_rejects_non_string_sql_with_structured_error() -> None:
    result = SQLTranspiler().transpile(cast(str, None), "mysql", "postgres")

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert result.error == "sql must be a string"


def test_transpile_rejects_non_string_source_with_structured_error() -> None:
    result = SQLTranspiler().transpile("SELECT 1", cast(str, None), "postgres")

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert result.error == "source must be a string"


def test_transpile_rejects_non_string_target_with_structured_error() -> None:
    result = SQLTranspiler().transpile("SELECT 1", "mysql", cast(str, None))

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert result.error == "target must be a string"
