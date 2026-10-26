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
                    {"name": "title"},
                    {"name": "is_deleted"},
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


@pytest.mark.parametrize(
    "text,expected",
    [
        ("show users not active", "status != 'active'"),
        ("show users not inactive", "status != 'inactive'"),
        ("show users not paid", "status != 'paid'"),
        ("show users not valid", "status != 'active'"),
        ("show users except active", "status != 'active'"),
        ("show users excluding active", "status != 'active'"),
        ("show users where status not 'active'", "status != 'active'"),
        ("不是有效用户", "status != 'active'"),
        ("非有效用户", "status != 'active'"),
    ],
)
@pytest.mark.parametrize("schema", [False, True])
def test_standalone_status_negation(text, expected, schema):
    result = generate(text, schema=schema)
    assert result.success
    assert expected in result.sql


@pytest.mark.parametrize(
    "text,expected",
    [
        ("description contains active", "description LIKE '%active%'"),
        ('description contains "active"', "description LIKE '%active%'"),
        ("name contains valid", "name LIKE '%valid%'"),
        ("title includes pending", "title LIKE '%pending%'")
    ],
)
@pytest.mark.parametrize("schema", [False, True])
def test_text_values_do_not_inject_status(text, expected, schema):
    if schema:
        text = f"show users where {text}"
    result = generate(text, schema=schema)
    assert result.success
    assert expected in result.sql
    assert "status =" not in result.sql
    assert "status !=" not in result.sql


@pytest.mark.parametrize("text", [
    "description contains active and price > 10",
    'description contains "active" and price > 10',
])
def test_text_and_numeric_conditions_are_preserved(text):
    result = generate(f"show users where {text}", schema=True)
    assert result.success
    assert "description LIKE '%active%'" in result.sql
    assert "price > 10" in result.sql
    assert "status =" not in result.sql
    assert "status !=" not in result.sql


@pytest.mark.parametrize(
    "text,expected_prefix,expected_condition",
    [
        ("已删除用户", "SELECT", "is_deleted = 1"),
        ("未删除用户", "SELECT", "is_deleted = 0"),
        ("没有删除的用户", "SELECT", "is_deleted = 0"),
        ("不是删除的用户", "SELECT", "is_deleted = 0"),
        ("删除用户", "DELETE", "DELETE FROM users"),
        ("delete users", "DELETE", "DELETE FROM users"),
        ("删除已删除用户", "DELETE", "is_deleted = 1"),
        ("show deleted users", "SELECT", "is_deleted = 1"),
    ],
)
@pytest.mark.parametrize("schema", [False, True])
def test_deleted_state_phrases_keep_operation_and_predicate(text, expected_prefix, expected_condition, schema):
    result = generate(text, schema=schema)
    assert result.success
    assert result.sql.lstrip().splitlines()[1].startswith(expected_prefix)
    assert expected_condition in result.sql


@pytest.mark.parametrize("dialect", ["postgres", "mysql"])
def test_remaining_status_and_text_cases_parse(dialect):
    for text in (
        "show users not active",
        "show users where status not 'active'",
        "show users where description contains active",
        "show users where price < -10",
    ):
        result = NL2SQLGenerator().generate(text, dialect, schema=SCHEMA)
        assert result.success
        assert sqlglot.parse_one(result.sql, read=dialect) is not None
