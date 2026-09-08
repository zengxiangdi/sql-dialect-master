"""AST-level regression tests for NL2SQL boolean conditions."""

import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator


nl2sql = NL2SQLGenerator()


def parse_sql(sql: str, dialect: str) -> exp.Expression:
    """Parse generated SQL with its target dialect."""
    return sqlglot.parse_one(sql, read=dialect)


def test_nl2sql_and_conditions_preserve_both_predicates():
    result = nl2sql.generate(
        "find products with price greater than 100 and quantity less than 10",
        "postgres",
    )

    assert result.success
    tree = parse_sql(result.sql, "postgres")
    where = tree.find(exp.Where)

    assert where is not None
    boolean = where.this
    assert isinstance(boolean, exp.And)
    assert len(list(boolean.find_all(exp.GT))) == 1
    assert len(list(boolean.find_all(exp.LT))) == 1
    assert {column.name.lower() for column in boolean.find_all(exp.Column)} >= {
        "price",
        "quantity",
    }


def test_nl2sql_or_conditions_preserve_both_predicates():
    result = nl2sql.generate(
        "find products with price greater than 100 or status active",
        "postgres",
    )

    assert result.success
    tree = parse_sql(result.sql, "postgres")
    where = tree.find(exp.Where)

    assert where is not None
    boolean = where.this
    assert isinstance(boolean, exp.Or)
    assert len(list(boolean.find_all(exp.GT))) == 1
    assert len(list(boolean.find_all(exp.EQ))) == 1
    assert "status" in {column.name.lower() for column in boolean.find_all(exp.Column)}


def test_nl2sql_chinese_and_conditions_preserve_boolean_structure():
    result = nl2sql.generate("查询价格大于100且数量小于10的产品", "postgres")

    assert result.success
    tree = parse_sql(result.sql, "postgres")
    where = tree.find(exp.Where)

    assert where is not None
    boolean = where.this
    assert isinstance(boolean, exp.And)
    columns = {column.name.lower() for column in boolean.find_all(exp.Column)}
    assert {"price", "quantity"}.issubset(columns)
