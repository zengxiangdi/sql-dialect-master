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


@pytest.mark.parametrize(
    "text,columns",
    [
        ("Show user 姓名 and nickname", ["name", "nickname"]),
        ("显示用户姓名和邮箱，附加 nickname", ["name", "email", "nickname"]),
        ("Show user emails and email", ["email"]),
        ("Show user names and name", ["name"]),
    ],
)
def test_schema_projection_merges_aliases_and_deduplicates(text, columns):
    result = generate(text)
    assert result.success
    assert f"SELECT {', '.join(columns)}" in result.sql


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Show user emails and email", "SELECT email\nFROM users"),
        ("Show user email and emails", "SELECT email\nFROM users"),
        ("Show user names and emails and name", "SELECT name, email\nFROM users"),
        ("Show user name and 姓名", "SELECT name\nFROM users"),
    ],
)
def test_schema_projection_deduplicates_canonical_columns(text, expected):
    result = generate(text)
    assert result.success
    assert expected in result.sql
    projection = result.sql.split("FROM", 1)[0]
    assert projection.count("email") <= 1
    assert projection.count("name") <= 1


def test_schema_projection_deduplication_keeps_alias_merge_behavior():
    result = generate("Show user 姓名 and nickname")
    assert result.success
    assert "SELECT name, nickname" in result.sql


@pytest.mark.parametrize(
    "text",
    [
        "show users where name = 'status'",
        "show users where name = 'users.email'",
    ],
)
def test_schema_projection_ignores_columns_inside_literals(text):
    result = generate(text)
    assert result.success
    assert "SELECT name" in result.sql
    assert "email" not in result.sql.split("FROM", 1)[0]


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


def test_schema_ordering_uses_target_column_after_projection_text():
    result = generate("Show users with name ordered by created_at")
    assert result.success
    assert "SELECT name" in result.sql
    assert "ORDER BY created_at ASC" in result.sql


def test_schema_unknown_ordering_column_fails_closed():
    result = generate("Show users ordered by missing_col")
    assert result.success is False
    assert result.sql is None


def test_schema_multiple_ordering_columns_fail_closed_until_batch_two():
    result = generate("Show users ordered by name and email")
    assert result.success is False
    assert result.sql is None


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


def test_no_schema_projection_and_ordering_outputs_remain_current():
    assert "SELECT *" in generate("Show user names and emails", schema=False).sql
    order_amounts = generate("Show all order amounts", schema=False)
    assert "ORDER BY" not in order_amounts.sql
    distinct = generate("Find distinct user emails", schema=False)
    assert "SELECT *" in distinct.sql
    ordered = generate("Show users ordered by created_at ascending", schema=False)
    assert "ORDER BY" not in ordered.sql

