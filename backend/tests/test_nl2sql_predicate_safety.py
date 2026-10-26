"""P0 regression coverage for deterministic predicate safety."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


SCHEMA = SchemaContext.from_mapping(
    {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id"},
                    {"name": "status"},
                    {"name": "price"},
                    {"name": "amount"},
                    {"name": "created_at"},
                    {"name": "description"},
                    {"name": "name"},
                ],
            },
            {
                "name": "orders",
                "columns": [
                    {"name": "id"},
                    {"name": "status"},
                    {"name": "user_id"},
                ],
            },
            {"name": "payments", "columns": [{"name": "order_id"}, {"name": "status"}]},
        ],
        "relationships": [
            {
                "from_table": "orders",
                "from_column": "user_id",
                "to_table": "users",
                "to_column": "id",
            },
            {
                "from_table": "payments",
                "from_column": "order_id",
                "to_table": "orders",
                "to_column": "id",
            },
        ],
    }
)


def generate(text: str, *, schema: bool = False):
    return NL2SQLGenerator().generate(
        text,
        "postgres",
        schema=SCHEMA if schema else None,
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("show active users", "status = 'active'"),
        ("show inactive users", "status = 'inactive'"),
        ("show users where status is active", "status = 'active'"),
        ("show users where status is not active", "status != 'active'"),
        ("show users where status != active", "status != 'active'"),
        ("show users where status <> active", "status != 'active'"),
        ("show users where status is not inactive", "status != 'inactive'"),
        ("show users where status is inactive", "status = 'inactive'"),
    ],
)
@pytest.mark.parametrize("schema", [False, True])
def test_status_predicates_are_consistent_with_and_without_schema(text, expected, schema):
    result = generate(text, schema=schema)
    assert result.success
    assert expected in result.sql
    assert "status = 'active'" not in result.sql or expected == "status = 'active'"


@pytest.mark.parametrize("text,expected", [
    ("price < -10", "price < -10"),
    ("amount >= -5.5", "amount >= -5.5"),
    ("价格 小于 -10", "price < -10"),
])
@pytest.mark.parametrize("schema", [False, True])
def test_signed_numeric_thresholds_are_preserved(text, expected, schema):
    if schema:
        text = f"show users where {text}"
    result = generate(text, schema=schema)
    assert result.success
    assert expected in result.sql


@pytest.mark.parametrize("text,expected", [
    ("created_at = '2024-01-01'", "created_at = '2024-01-01'"),
    ("created_at > '2024-01-01'", "created_at > '2024-01-01'"),
    ('created_at = "2024-01-01"', "created_at = '2024-01-01'"),
    ('description contains "active"', "description LIKE '%active%'"),
    ("name = 'active'", "name = 'active'"),
])
@pytest.mark.parametrize("schema", [False, True])
def test_quoted_literals_are_not_truncated_or_reinterpreted(text, expected, schema):
    if schema:
        text = f"show users where {text}"
    result = generate(text, schema=schema)
    assert result.success
    assert expected in result.sql
    if "description" in text:
        assert "status = 'active'" not in result.sql


@pytest.mark.parametrize("schema", [False, True])
def test_status_negation_and_numeric_condition_compose(schema):
    result = generate(
        "show users where status is not active and price > 10",
        schema=schema,
    )
    assert result.success
    assert "status != 'active'" in result.sql
    assert "price > 10" in result.sql


@pytest.mark.parametrize("text,expected", [
    ("未支付订单", "status = 'unpaid'"),
    ("已支付订单", "status = 'paid'"),
])
def test_chinese_payment_status_semantics_remain(text, expected):
    result = generate(text)
    assert result.success
    assert expected in result.sql


@pytest.mark.parametrize("dialect", ["postgres", "mysql"])
def test_safe_predicates_parse_in_supported_dialects(dialect):
    result = NL2SQLGenerator().generate(
        "show users where status is not active and price < -10",
        dialect,
        schema=SCHEMA,
    )
    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_predicate_results_are_deterministic():
    first = generate("show users where status is not active and price < -10", schema=True)
    second = generate("show users where status is not active and price < -10", schema=True)
    assert first.success and second.success
    assert first.sql == second.sql
