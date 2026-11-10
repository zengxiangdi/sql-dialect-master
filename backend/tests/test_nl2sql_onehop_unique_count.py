"""Composite subject identity counts over one-hop relationships."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def context(*, complete=True, subject_pk=True, target_pk=True, extra=None):
    tables = [
        {"name": "users", "columns": [{"name": "tenant_id"}, {"name": "id"}]},
        {"name": "orders", "columns": [
            {"name": "tenant_id"}, {"name": "id"}, {"name": "user_id"},
        ]},
    ]
    if subject_pk:
        tables[0]["primary_key"] = ["tenant_id", "id"]
    if target_pk:
        tables[1]["primary_key"] = ["id"]
    relationships = [
        {
            "from_table": "orders",
            "to_table": "users",
            "columns": [
                {"from_column": "tenant_id", "to_column": "tenant_id"},
                {"from_column": "user_id", "to_column": "id"},
            ],
        }
        if complete
        else {
            "from_table": "orders",
            "from_column": "user_id",
            "to_table": "users",
            "to_column": "id",
        }
    ]
    if extra:
        relationships.extend(extra)
    return SchemaContext.from_mapping({"tables": tables, "relationships": relationships})


def generate(text, schema_context=None, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema_context)


def test_composite_subject_onehop_exact_sql():
    result = generate("count distinct orders per user", context())

    assert result.success
    assert result.sql == (
        "-- Generated for POSTGRES\n"
        "SELECT _group_0, _group_1, COUNT(*) AS count\n"
        "FROM (\n"
        "    SELECT DISTINCT users.tenant_id AS _group_0, users.id AS _group_1, orders.id AS _target_0\n"
        "    FROM users\n"
        "    JOIN orders ON users.tenant_id = orders.tenant_id AND users.id = orders.user_id\n"
        "    WHERE users.tenant_id IS NOT NULL AND users.id IS NOT NULL AND orders.id IS NOT NULL\n"
        ") AS _distinct_targets\n"
        "GROUP BY _group_0, _group_1"
    )


def test_subject_whose_and_outer_limit():
    result = generate(
        "count distinct orders per user whose tenant_id is 1 limit 5",
        context(),
    )

    assert result.success
    assert "WHERE users.tenant_id = 1" in result.sql
    assert result.sql.index(") AS _distinct_targets") < result.sql.index("LIMIT 5")


@pytest.mark.parametrize("text", [
    "count distinct orders per user where tenant_id = 1",
    "count distinct orders per user whose orders.id is 1",
    "count distinct orders per user ordered by tenant_id",
])
def test_unsupported_onehop_filters_and_order_fail_closed(text):
    result = generate(text, context())

    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("kwargs", [
    {"complete": False},
    {"subject_pk": False},
    {"target_pk": False},
])
def test_incomplete_relationship_or_identity_fails_closed(kwargs):
    result = generate("count distinct orders per user", context(**kwargs))

    assert result.success is False
    assert result.sql is None


def test_multiple_direct_relationships_fail_closed():
    result = generate(
        "count distinct orders per user",
        context(extra=[{
            "from_table": "orders",
            "from_column": "id",
            "to_table": "users",
            "to_column": "id",
        }]),
    )

    assert result.success is False
    assert result.sql is None


def test_duplicate_rows_and_tenant_identity_are_distinct_in_sqlite():
    result = generate("count distinct orders per user", context())
    assert result.success
    sql = result.sql.split("\n", 1)[1]
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE users(tenant_id INTEGER, id INTEGER);"
        "CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER);"
        "INSERT INTO users VALUES (1, 1), (2, 1);"
        "INSERT INTO orders VALUES (1, 1, 1), (1, 1, 1), (1, 2, 1), (2, 3, 1);"
    )

    assert list(connection.execute(sql)) == [(1, 1, 2), (2, 1, 1)]


def test_onehop_single_subject_pk_keeps_existing_count_distinct():
    mapping = {
        "tables": [
            {"name": "users", "columns": [{"name": "id"}], "primary_key": ["id"]},
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}], "primary_key": ["id"]},
        ],
        "relationships": [{
            "from_table": "orders",
            "from_column": "user_id",
            "to_table": "users",
            "to_column": "id",
        }],
    }
    result = generate("count distinct orders per user", SchemaContext.from_mapping(mapping))

    assert result.success
    assert "SELECT user_id, COUNT(DISTINCT id) AS count" in result.sql
    assert "_group_0" not in result.sql


def test_no_schema_remains_unchanged():
    result = generate("count distinct orders per user")

    assert result.success
    assert result.schema_used is False
    assert "SELECT DISTINCT user_id, COUNT(*) AS count" in result.sql


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_onehop_composite_count_is_parseable_in_all_dialects(dialect):
    result = generate("count distinct orders per user", context(), dialect=dialect)

    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_onehop_generation_is_deterministic():
    first = generate("count distinct orders per user whose tenant_id is 1 limit 5", context())
    second = generate("count distinct orders per user whose tenant_id is 1 limit 5", context())

    assert first.success and second.success
    assert first.sql == second.sql
    assert first.explanation == second.explanation
