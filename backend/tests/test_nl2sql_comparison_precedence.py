"""Regression tests for comparison operator precedence in NL2SQL."""

import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator


def _where(text: str) -> exp.Expression:
    result = NL2SQLGenerator().generate(text, "postgres")
    assert result.success
    tree = sqlglot.parse_one(result.sql, read="postgres")
    where = tree.find(exp.Where)
    assert where is not None
    return where.this


def test_greater_than_or_equal_is_not_reduced_to_greater_than():
    where = _where("查询价格大于等于100的产品")
    assert len(list(where.find_all(exp.GTE))) == 1
    assert not list(where.find_all(exp.GT))


def test_less_than_or_equal_is_not_reduced_to_less_than():
    where = _where("查询价格小于等于100的产品")
    assert len(list(where.find_all(exp.LTE))) == 1
    assert not list(where.find_all(exp.LT))
