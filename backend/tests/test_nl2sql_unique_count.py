"""Schema-aware unique entity count contracts for single-column identities."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def make_schema(*, primary_key=None, products=False):
    users = {
        "name": "users",
        "columns": [{"name": "id"}],
        "primary_key": ["id"],
    }
    orders = {
        "name": "orders",
        "columns": [
            {"name": "id"},
            {"name": "user_id"},
            {"name": "amount"},
            {"name": "status"},
        ],
    }
    if primary_key is not None:
        orders["primary_key"] = primary_key
    tables = [users, orders]
    relationships = [{
        "from_table": "orders",
        "from_column": "user_id",
        "to_table": "users",
        "to_column": "id",
    }]
    if products:
        tables.append({"name": "products", "columns": [{"name": "id"}]})
        relationships.append({
            "from_table": "orders",
            "from_column": "id",
            "to_table": "products",
            "to_column": "id",
        })
    return SchemaContext.from_mapping({"tables": tables, "relationships": relationships})


def generate(text, schema=None):
    return NL2SQLGenerator().generate(text, "postgres", schema=schema)


@pytest.mark.parametrize("text", [
    "count distinct orders",
    "count unique orders",
    "number of distinct orders",
    "不同订单数",
])
def test_explicit_unique_count_without_group(text):
    result = generate(text, make_schema(primary_key=["id"]))
    assert result.success
    assert result.sql == "-- Generated for POSTGRES\nSELECT COUNT(DISTINCT id) AS count\nFROM orders"


@pytest.mark.parametrize("text", [
    "count distinct orders per user",
    "count unique orders per user",
    "number of distinct orders per user",
    "每个用户的不同订单数",
    "每个用户的去重订单数",
    "每个用户的唯一订单数",
])
def test_explicit_unique_count_preserves_grouping(text):
    result = generate(text, make_schema(primary_key=["id"]))
    assert result.success
    assert "SELECT user_id, COUNT(DISTINCT id) AS count" in result.sql
    assert "FROM orders" in result.sql
    assert "GROUP BY user_id" in result.sql
    assert "SELECT DISTINCT" not in result.sql


def test_unique_count_preserves_where_and_whose_conditions():
    where = generate(
        "count distinct orders per user where amount > 10",
        make_schema(primary_key=["id"]),
    )
    whose = generate(
        "count distinct orders whose status is active",
        make_schema(primary_key=["id"]),
    )

    assert where.success
    assert "COUNT(DISTINCT id) AS count" in where.sql
    assert "WHERE amount > 10" in where.sql
    assert "GROUP BY user_id" in where.sql
    assert whose.success
    assert "COUNT(DISTINCT id) AS count" in whose.sql
    assert "WHERE status = 'active'" in whose.sql


def test_plain_count_and_non_count_language_remain_unchanged():
    count = generate("count orders per user", make_schema(primary_key=["id"]))
    chinese = generate("订单数量", make_schema(primary_key=["id"]))
    projection = generate("find distinct orders", make_schema(primary_key=["id"]))

    assert count.success
    assert "COUNT(*) AS count" in count.sql
    assert "COUNT(DISTINCT" not in count.sql
    assert chinese.success
    assert "COUNT(*) AS count" in chinese.sql
    assert "COUNT(DISTINCT" not in chinese.sql
    assert projection.success
    assert "SELECT DISTINCT *" in projection.sql


@pytest.mark.parametrize("primary_key", [None])
def test_missing_primary_key_fails_closed(primary_key):
    result = generate("count distinct orders", make_schema(primary_key=primary_key))
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "count distinct users joined with orders",
    "count distinct users joined on orders.user_id = users.id",
    "count distinct users who have products",
])
def test_relationships_and_paths_fail_closed(text):
    result = generate(text, make_schema(primary_key=["id"], products=True))
    assert result.success is False
    assert result.sql is None


def test_distinct_projection_and_unique_count_fail_closed():
    result = generate(
        "show distinct orders and count unique orders",
        make_schema(primary_key=["id"]),
    )
    assert result.success is False
    assert result.sql is None


def test_non_count_aggregation_and_unique_count_fail_closed():
    result = generate(
        "count distinct orders and average amount",
        make_schema(primary_key=["id"]),
    )
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_unique_count_is_parseable_in_all_dialects(dialect):
    result = NL2SQLGenerator().generate(
        "count distinct orders per user",
        dialect,
        schema=make_schema(primary_key=["id"]),
    )
    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_sqlite_unique_count_runtime_with_duplicate_rows():
    result = generate("count distinct orders per user", make_schema(primary_key=["id"]))
    assert result.success
    sql = result.sql.split("\n", 1)[1]
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE orders(id INTEGER, user_id INTEGER, amount INTEGER);"
        "INSERT INTO orders VALUES (1, 10, 5), (1, 10, 7), (2, 10, 9), (3, 20, 4);"
    )
    assert list(connection.execute(sql)) == [(10, 2), (20, 1)]


def test_unique_count_is_deterministic():
    schema = make_schema(primary_key=["id"])
    first = generate("count distinct orders per user", schema)
    second = generate("count distinct orders per user", schema)
    assert first.success and second.success
    assert first.sql == second.sql


@pytest.mark.parametrize("text", [
    "count distinct orders per user",
    "count distinct orders",
    "count orders per user",
    "订单数量",
    "find distinct orders",
])
def test_no_schema_outputs_are_unchanged_and_deterministic(text):
    first = generate(text)
    second = generate(text)
    assert first.success == second.success
    assert first.sql == second.sql
    assert first.schema_used is False
