"""P1 schema-aware projection and DISTINCT contracts."""

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
                    {"name": "id"}, {"name": "name"}, {"name": "email"},
                    {"name": "nickname"}, {"name": "created_at"}, {"name": "user_id"},
                ],
            },
            {
                "name": "orders",
                "columns": [{"name": "id"}, {"name": "amount"}, {"name": "user_id"}],
            },
        ],
        "relationships": [{
            "from_table": "orders", "from_column": "user_id",
            "to_table": "users", "to_column": "id",
        }],
    }
)


def generate(text: str, *, schema: bool = True, hints=None):
    return NL2SQLGenerator().generate(
        text,
        "postgres",
        column_hints=hints,
        schema=SCHEMA if schema else None,
    )


@pytest.mark.parametrize(
    "text,columns",
    [
        ("Show user names and emails", ["name", "email"]),
        ("Show user name and email", ["name", "email"]),
        ("Show user emails", ["email"]),
        ("Show user email", ["email"]),
        ("Show user names and nickname", ["name", "nickname"]),
        ("Show user NAMES and EMAILS", ["name", "email"]),
    ],
)
def test_schema_projection_uses_text_order_and_case_insensitive_columns(text, columns):
    result = generate(text)
    assert result.success
    assert f"SELECT {', '.join(columns)}" in result.sql


def test_schema_projection_supports_qualified_column():
    qualified = SchemaContext.from_mapping({
        "tables": [{"name": "public.users", "columns": [{"name": "email"}]}]
    })
    result = NL2SQLGenerator().generate(
        "show public.users.email", "postgres", schema=qualified
    )
    assert result.success
    assert "SELECT email" in result.sql


def test_schema_projection_rejects_mapped_column_outside_table():
    result = generate("Show user names and age")
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Find distinct user emails", "SELECT DISTINCT email"),
        ("Find distinct users", "SELECT DISTINCT *"),
    ],
)
def test_schema_distinct_combines_with_projection(text, expected):
    result = generate(text)
    assert result.success
    assert expected in result.sql


@pytest.mark.parametrize("text", ["Show all order amounts", "Show all amounts from orders"])
def test_schema_projection_does_not_add_spurious_ordering(text):
    result = generate(text)
    assert result.success
    assert "SELECT amount" in result.sql
    assert "ORDER BY" not in result.sql


@pytest.mark.parametrize(
    "text,order",
    [
        ("Show users ordered by created_at ascending", "ORDER BY created_at ASC"),
        ("Show users ordered by created_at descending", "ORDER BY created_at DESC"),
        ("Show users sorted by created_at", "ORDER BY created_at ASC"),
    ],
)
def test_schema_explicit_ordering_is_preserved(text, order):
    result = generate(text)
    assert result.success
    assert order in result.sql


def test_schema_plain_select_and_exists_are_unchanged():
    plain = generate("Show users")
    exists = generate("users who have orders")
    assert plain.success and "SELECT *" in plain.sql
    assert exists.success and "WHERE EXISTS" in exists.sql


def test_schema_column_hints_remain_authoritative():
    result = generate("Show users", hints=["users.email", "users.name"])
    assert result.success
    assert "SELECT users.email, users.name" in result.sql


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_schema_projection_parses_in_all_dialects(dialect):
    result = NL2SQLGenerator().generate("Show user names and emails", dialect, schema=SCHEMA)
    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Show user names and emails",
        "Show all order amounts",
        "Find distinct user emails",
        "Show users ordered by created_at ascending",
    ],
)
def test_no_schema_projection_outputs_remain_current(text):
    first = generate(text, schema=False)
    second = generate(text, schema=False)
    assert first.success == second.success
    assert first.sql == second.sql
    assert first.schema_used is False

