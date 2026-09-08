"""Regression tests for negative NULL predicate precedence in NL2SQL."""

import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator


def _where_conditions(text: str):
    result = NL2SQLGenerator().generate(text, "postgres")
    assert result.success
    tree = sqlglot.parse_one(result.sql, read="postgres")
    where = tree.find(exp.Where)
    assert where is not None
    return where.this


def test_is_not_null_does_not_generate_is_null():
    where = _where_conditions("find products with description is not null")
    assert len(list(where.find_all(exp.Is))) == 1
    rendered = where.sql(dialect="postgres").upper()
    assert " IS NOT NULL" in rendered
    assert " IS NULL" not in rendered


def test_chinese_non_empty_does_not_generate_is_null():
    where = _where_conditions("查询描述非空的产品")
    assert len(list(where.find_all(exp.Is))) == 1
    rendered = where.sql(dialect="postgres").upper()
    assert " IS NOT NULL" in rendered
    assert " IS NULL" not in rendered
