import pytest

from backend.core.nl2sql import NL2SQLGenerator


def test_oracle_date_adjustment_preserves_parentheses():
    generator = NL2SQLGenerator()
    sql = "SELECT COALESCE(amount, 0) FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)"

    result = generator._apply_dialect_adjustments(sql, "oracle")

    assert "COALESCE(amount, 0)" in result
    assert "TRUNC(SYSDATE) - 7" in result
    assert result.count("(") == result.count(")")


def test_tsql_date_adjustment_builds_valid_dateadd_expression():
    generator = NL2SQLGenerator()
    sql = "SELECT COALESCE(amount, 0) FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)"

    result = generator._apply_dialect_adjustments(sql, "tsql")

    assert "COALESCE(amount, 0)" in result
    assert "DATEADD(DAY, -7, CAST(GETDATE() AS DATE))" in result
    assert result.count("(") == result.count(")")


def test_postgres_date_adjustment_expands_backreference():
    generator = NL2SQLGenerator()
    sql = "SELECT * FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)"

    result = generator._apply_dialect_adjustments(sql, "postgres")

    assert "CURRENT_DATE - INTERVAL '7 days'" in result
    assert "\\1 days" not in result


def test_nl2sql_normalizes_direct_dialect_input():
    generator = NL2SQLGenerator()

    result = generator.generate("查询所有用户", " MySQL ")

    assert result.success
    assert result.dialect == "mysql"


def test_nl2sql_rejects_unsupported_direct_dialect():
    generator = NL2SQLGenerator()

    with pytest.raises(ValueError, match="Unsupported dialect"):
        generator.generate("查询所有用户", "not-a-dialect")


def test_nl2sql_rejects_non_string_text():
    generator = NL2SQLGenerator()

    with pytest.raises(TypeError, match="text must be a string"):
        generator.generate(None, "mysql")
