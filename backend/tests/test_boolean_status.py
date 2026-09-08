"""Regression tests for English and Chinese status predicates in booleans."""

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


def test_chinese_status_predicate_is_preserved_with_or():
    boolean = parse_where("查询价格大于100或状态为有效的产品")

    assert isinstance(boolean, exp.Or)
    assert isinstance(boolean.this, exp.Paren)
    assert isinstance(boolean.expression, exp.Paren)
    assert isinstance(boolean.this.this, exp.GT)
    assert isinstance(boolean.expression.this, exp.EQ)
    assert boolean.expression.this.this.name.lower() == "status"


def test_chinese_status_predicate_is_preserved_with_and():
    boolean = parse_where("查询数量小于10且状态为无效的产品")

    assert isinstance(boolean, exp.And)
    assert isinstance(boolean.this, exp.Paren)
    assert isinstance(boolean.expression, exp.Paren)
    assert isinstance(boolean.expression.this, exp.EQ)
    assert boolean.expression.this.this.name.lower() == "status"


def test_mixed_english_and_chinese_status_aliases():
    boolean = parse_where("find products with price greater than 100 and 状态为已完成")

    assert isinstance(boolean, exp.And)
    assert len(list(boolean.find_all(exp.GT))) == 1
    status_eq = [node for node in boolean.find_all(exp.EQ) if node.this.name.lower() == "status"]
    assert len(status_eq) == 1
    assert status_eq[0].expression.name == "completed"
