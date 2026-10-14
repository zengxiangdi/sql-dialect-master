"""Regression tests for output delimiters and PostgreSQL ROUND overloads."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from backend.core.transpiler import SQLTranspiler
from frontend.app_context_v2 import format_sql_local


def test_transpile_preserves_terminal_semicolon_without_confusing_literals_or_comments() -> None:
    transpiler = SQLTranspiler()

    for sql in ("SELECT 1;", "SELECT 1; -- trailing comment\n"):
        result = transpiler.transpile(sql, "mysql", "postgres", pretty=False)
        assert result.success, result.error
        assert result.target_sql and result.target_sql.rstrip().endswith(";")

    for sql in ("SELECT ';'", "SELECT 1 /* ; */"):
        result = transpiler.transpile(sql, "mysql", "postgres", pretty=False)
        assert result.success, result.error
        assert result.target_sql and not result.target_sql.rstrip().endswith(";")


def test_format_preserves_terminal_semicolon() -> None:
    assert format_sql_local("SELECT 1;", "mysql").rstrip().endswith(";")
    assert not format_sql_local("SELECT 1", "mysql").rstrip().endswith(";")


def test_postgres_two_argument_round_casts_value_to_numeric() -> None:
    sql = """
    SELECT
      ROUND(SUM(amount), 2),
      ROUND(100 * SUM(amount) / NULLIF(SUM(total), 0), 2),
      ROUND(CAST(amount AS DOUBLE), 2)
    FROM orders;
    """
    result = SQLTranspiler().transpile(sql, "mysql", "postgres", pretty=False)
    assert result.success, result.error
    assert result.target_sql

    tree = sqlglot.parse_one(result.target_sql, read="postgres")
    rounds = list(tree.find_all(exp.Round))
    assert len(rounds) == 3
    assert all(isinstance(node.this, exp.Cast) for node in rounds)
    assert all(node.args.get("decimals") is not None for node in rounds)
    assert all(node.this.args["to"].this == exp.DataType.Type.DECIMAL for node in rounds)
