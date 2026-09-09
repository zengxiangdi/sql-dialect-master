"""Regression tests for second-pass production hardening."""

from backend.core.config import settings
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.parser import SQLParser
from backend.core.transpiler import SQLTranspiler


def test_transpile_rejects_oversized_sql_before_security_scan() -> None:
    sql = "SELECT 1 " + ("x" * settings.transpiler_max_sql_length)
    result = SQLTranspiler().transpile(sql, "mysql", "postgres")
    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert "maximum length" in (result.error or "")


def test_parser_rejects_oversized_sql_before_sqlglot() -> None:
    sql = "SELECT 1 " + ("x" * settings.transpiler_max_sql_length)
    result = SQLParser("mysql").parse(sql)
    assert result.success is False
    assert "maximum length" in (result.error or "")


def test_nl2sql_rejects_oversized_text_before_processing() -> None:
    text = "查询" + ("用户" * 5000)
    result = NL2SQLGenerator("mysql").generate(text)
    assert result.success is False
    assert "maximum length" in result.explanation


def test_nl2sql_non_string_input_preserves_type_contract() -> None:
    try:
        NL2SQLGenerator("mysql").generate(None)  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "text must be a string"
    else:
        raise AssertionError("Expected TypeError for non-string NL2SQL input")


def test_target_output_validation_reports_syntax_failure() -> None:
    transpiler = SQLTranspiler()
    error = transpiler._validate_output("SELECT definitely_not_valid__(", "postgres")
    assert error is not None
    assert "Output SQL may have syntax issues" in error
