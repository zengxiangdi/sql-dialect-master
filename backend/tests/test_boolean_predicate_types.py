"""Regression tests for boolean range, text, and NULL predicates."""

import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator


nl2sql = NL2SQLGenerator()


def parse_where(text: str) -> exp.Expression:
    result = nl2sql.generate(text, "postgres")
    assert result.success
    tree = sqlglot.parse_one(result.sql, read="postgres")
    where = tree.find(exp.Where)
    assert where is not None
    return where.this


def test_range_predicate_is_preserved_with_or():
    boolean = parse_where("find products with price between 10 and 20 or status active")
    assert isinstance(boolean, exp.Or)
    assert len(list(boolean.find_all(exp.Between))) == 1
    assert any(
        node.this.name.lower() == "status" and node.expression.name == "active"
        for node in boolean.find_all(exp.EQ)
    )


def test_contains_predicate_is_preserved_with_and():
    boolean = parse_where("find products with name containing phone and price greater than 100")
    assert isinstance(boolean, exp.And)
    assert len(list(boolean.find_all(exp.Like))) == 1
    assert len(list(boolean.find_all(exp.GT))) == 1


def test_null_predicate_is_preserved_with_or():
    boolean = parse_where("find products with description is null or status active")
    assert isinstance(boolean, exp.Or)
    assert len(list(boolean.find_all(exp.Is))) == 1
    assert any(
        node.this.name.lower() == "status" and node.expression.name == "active"
        for node in boolean.find_all(exp.EQ)
    )


def test_chinese_range_and_null_predicates_preserve_connectors():
    boolean = parse_where("查询价格在10到20之间且描述为空或状态为已完成的产品")
    assert isinstance(boolean, exp.Or)
    assert isinstance(boolean.this, exp.And)
    assert len(list(boolean.find_all(exp.Between))) == 1
    assert len(list(boolean.find_all(exp.Is))) == 1
    status_eq = [
        node for node in boolean.find_all(exp.EQ) if node.this.name.lower() == "status"
    ]
    assert len(status_eq) == 1
    assert status_eq[0].expression.name == "completed"
