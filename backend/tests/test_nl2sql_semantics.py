import pytest
import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator


def test_bottom_n_template_orders_ascending():
    result = NL2SQLGenerator().generate("find bottom 10 products by price", "postgres")
    assert result.success
    assert "ORDER BY price ASC" in result.sql
    assert "LIMIT 10" in result.sql


def test_top_n_template_keeps_descending_order():
    result = NL2SQLGenerator().generate("find top 10 products by price", "postgres")
    assert result.success
    assert "ORDER BY price DESC" in result.sql
    assert "LIMIT 10" in result.sql


def test_table_hint_accepts_dotted_identifier():
    result = NL2SQLGenerator().generate("show all users", "postgres", "analytics.users")
    assert result.success
    assert "FROM analytics.users" in result.sql


def test_table_hint_rejects_sql_injection_syntax():
    with pytest.raises(ValueError, match="simple SQL identifier"):
        NL2SQLGenerator().generate("show all users", "postgres", "users; DROP TABLE orders")


def test_bottom_n_output_remains_parseable():
    result = NL2SQLGenerator().generate("find bottom 5 products by price", "postgres")
    assert result.success
    parsed = sqlglot.parse_one(result.sql, read="postgres")
    order = parsed.find(exp.Order)
    assert order is not None
    assert order.expressions[0].args.get("desc") is False
