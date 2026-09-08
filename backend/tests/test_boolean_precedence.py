"""AST regressions for mixed boolean precedence and explicit parentheses."""

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


def test_mixed_and_or_uses_sql_precedence():
    boolean = parse_where(
        "find products with price greater than 100 and quantity less than 10 or status active"
    )

    assert isinstance(boolean, exp.Or)
    assert isinstance(boolean.this, exp.And)
    assert len(list(boolean.find_all(exp.GT))) == 1
    assert len(list(boolean.find_all(exp.LT))) == 1
    assert len(list(boolean.find_all(exp.EQ))) == 1


def test_parentheses_override_and_or_precedence():
    boolean = parse_where(
        "find products with (price greater than 100 or quantity less than 10) and status active"
    )

    assert isinstance(boolean, exp.And)
    assert isinstance(boolean.this, exp.Paren)
    inner = boolean.this.this
    assert isinstance(inner, exp.Or)
    assert isinstance(boolean.expression, exp.EQ)


def test_chinese_mixed_boolean_conditions_preserve_connectors():
    boolean = parse_where("查询价格大于100且数量小于10或状态为有效的产品")

    assert isinstance(boolean, exp.Or)
    assert isinstance(boolean.this, exp.And)
    assert {column.name.lower() for column in boolean.find_all(exp.Column)} >= {
        "price",
        "quantity",
        "status",
    }
