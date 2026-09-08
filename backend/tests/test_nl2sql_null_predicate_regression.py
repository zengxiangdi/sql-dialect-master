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
    return list(where.this.walk()), where.this


def test_is_not_null_does_not_generate_is_null():
    nodes, where = _where_conditions("find products with description is not null")
    is_nodes = list(where.find_all(exp.Is))
    assert len(is_nodes) == 1
    assert any(isinstance(node, exp.Not) for node in nodes)


def test_chinese_non_empty_does_not_generate_is_null():
    nodes, where = _where_conditions("查询描述非空的产品")
    is_nodes = list(where.find_all(exp.Is))
    assert len(is_nodes) == 1
    assert any(isinstance(node, exp.Not) for node in nodes)
