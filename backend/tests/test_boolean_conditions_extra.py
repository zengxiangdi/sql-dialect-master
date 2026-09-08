"""Additional AST-level boolean condition regressions."""

from sqlglot import exp

from backend.tests.test_boolean_conditions import parse_sql, nl2sql


def test_nl2sql_boolean_and_has_two_comparison_nodes():
    result = nl2sql.generate("find products with price greater than 100 and quantity less than 10", "postgres")
    assert result.success
    where = parse_sql(result.sql, "postgres").find(exp.Where)
    assert where is not None
    assert isinstance(where.this, exp.And)


def test_nl2sql_boolean_or_has_two_comparison_nodes():
    result = nl2sql.generate("find products with price greater than 100 or status active", "postgres")
    assert result.success
    where = parse_sql(result.sql, "postgres").find(exp.Where)
    assert where is not None
    assert isinstance(where.this, exp.Or)
