"""AST regressions for IN / NOT IN boolean predicates."""

import time

import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_components.boolean_conditions import extract_boolean_conditions


nl2sql = NL2SQLGenerator()


def parse_where(text: str) -> exp.Expression:
    result = nl2sql.generate(text, "postgres")
    assert result.success
    tree = sqlglot.parse_one(result.sql, read="postgres")
    where = tree.find(exp.Where)
    assert where is not None
    return where.this


def test_english_in_predicate_is_preserved_with_and():
    boolean = parse_where("find products where category in ('electronics', 'books') and price greater than 100")
    assert isinstance(boolean, exp.And)
    assert isinstance(boolean.this, exp.Paren)
    assert isinstance(boolean.this.this, exp.In)
    assert len(list(boolean.this.this.expressions)) == 2
    assert isinstance(boolean.expression, exp.Paren)
    assert isinstance(boolean.expression.this, exp.GT)


def test_english_not_in_predicate_is_preserved_with_or():
    boolean = parse_where("find products where status not in ('inactive', 'deleted') or quantity less than 10")
    assert isinstance(boolean, exp.Or)
    assert isinstance(boolean.this, exp.Paren)
    assert isinstance(boolean.this.this, exp.Not)
    assert isinstance(boolean.this.this.this, exp.In)
    assert isinstance(boolean.expression, exp.Paren)
    assert isinstance(boolean.expression.this, exp.LT)


def test_chinese_in_predicate_is_preserved_with_status():
    boolean = parse_where("查询类别在电子,书籍中且状态为有效的产品")
    assert isinstance(boolean, exp.And)
    assert isinstance(boolean.this, exp.Paren)
    assert isinstance(boolean.this.this, exp.In)
    assert isinstance(boolean.expression, exp.Paren)
    assert isinstance(boolean.expression.this, exp.EQ)
    assert boolean.expression.this.this.name.lower() == "status"


def test_chinese_not_in_predicate_is_preserved_with_comparison():
    boolean = parse_where("查询地区不在北美,欧洲中或价格大于100的产品")
    assert isinstance(boolean, exp.Or)
    assert isinstance(boolean.this, exp.Paren)
    assert isinstance(boolean.this.this, exp.Not)
    assert isinstance(boolean.this.this.this, exp.In)
    assert isinstance(boolean.expression, exp.Paren)
    assert isinstance(boolean.expression.this, exp.GT)


def test_chinese_set_predicate_handles_long_uncontrolled_value_linearly():
    values = ",".join(f"value{i}" for i in range(5000))
    text = f"查询类别在{values}中且价格大于100的产品"

    started = time.monotonic()
    conditions = extract_boolean_conditions(text)
    elapsed = time.monotonic() - started

    assert conditions
    assert elapsed < 2.0
