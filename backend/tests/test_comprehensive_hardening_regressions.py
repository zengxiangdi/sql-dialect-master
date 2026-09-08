"""Regression tests for the final comprehensive hardening pass."""

import asyncio

import sqlglot
from sqlglot import exp

from backend.api import main
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.parser import SQLParser
from backend.core.post_processor import PostProcessor


def test_mysql_group_concat_without_separator_uses_comma():
    processed, _ = PostProcessor().process("SELECT GROUP_CONCAT(name) FROM users", "mysql", "postgres")
    assert "STRING_AGG(name::TEXT, ',')" in processed


def test_oracle_decode_null_search_preserves_null_semantics():
    processed, _ = PostProcessor().process(
        "SELECT DECODE(status, NULL, 'missing', 'set') FROM users",
        "oracle",
        "postgres",
    )
    assert "WHEN status IS NULL THEN 'missing'" in processed
    assert "status = NULL" not in processed


def test_parser_normalizes_dialect_whitespace():
    parser = SQLParser(" MySQL ")
    assert parser.dialect == "mysql"


def test_parser_counts_aggregate_function_without_group_by():
    result = SQLParser("postgres").extract_elements("SELECT COUNT(*) FROM users")
    assert result["has_aggregation"] is True


def test_parse_api_reports_invalid_sql_as_failure():
    class Request:
        sql = "SELECT FROM"
        dialect = "postgres"

    response = asyncio.run(main.parse_sql(Request()))
    assert response["success"] is False
    assert "error" in response


def test_english_inclusive_comparison_preserves_greater_equal():
    result = NL2SQLGenerator().generate(
        "find products with price greater than or equal to 10", "postgres"
    )
    assert result.success
    tree = sqlglot.parse_one(result.sql, read="postgres")
    where = tree.find(exp.Where)
    assert where is not None
    assert len(list(where.find_all(exp.GTE))) == 1
    assert len(list(where.find_all(exp.GT))) == 0


def test_english_inclusive_comparison_preserves_less_equal():
    result = NL2SQLGenerator().generate(
        "find products with price less than or equal to 10", "postgres"
    )
    assert result.success
    tree = sqlglot.parse_one(result.sql, read="postgres")
    where = tree.find(exp.Where)
    assert where is not None
    assert len(list(where.find_all(exp.LTE))) == 1
    assert len(list(where.find_all(exp.LT))) == 0
