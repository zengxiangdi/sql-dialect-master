"""Phase 2 schema-aware composite-primary-key unique count contracts."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def schema(*, primary_key=None, include_products=False):
    tables = [
        {
            "name": "users",
            "columns": [{"name": "id"}],
            "primary_key": ["id"],
        },
        {
            "name": "orders",
            "columns": [
                {"name": "tenant_id"},
                {"name": "id"},
                {"name": "user_id"},
                {"name": "amount"},
                {"name": "status"},
            ],
        },
    ]
    if primary_key is not None:
        tables[1]["primary_key"] = primary_key
    relationships = [{
        "from_table": "orders",
        "from_column": "user_id",
        "to_table": "users",
        "to_column": "id",
    }]
    if include_products:
        tables.append({"name": "products", "columns": [{"name": "id"}]})
        relationships.append({
            "from_table": "orders",
            "from_column": "id",
            "to_table": "products",
            "to_column": "id",
        })
    return SchemaContext.from_mapping({
        "tables": tables,
        "relationships": relationships,
    })


def generate(text, schema_context=None, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema_context)


def test_composite_pk_grouped_sql():
    result = generate("count distinct orders per user", schema(primary_key=["tenant_id", "id"]))

    assert result.success
    assert result.sql == (
        "-- Generated for POSTGRES\n"
        "SELECT user_id, COUNT(*) AS count\n"
        "FROM (\n"
        "    SELECT DISTINCT user_id, tenant_id, id\n"
        "    FROM orders\n"
        "    WHERE tenant_id IS NOT NULL AND id IS NOT NULL\n"
        ") AS _distinct_targets\n"
        "GROUP BY user_id"
    )


def test_composite_pk_scalar_sql():
    result = generate("count distinct orders", schema(primary_key=["tenant_id", "id"]))

    assert result.success
    assert "SELECT COUNT(*) AS count" in result.sql
    assert "SELECT DISTINCT tenant_id, id" in result.sql
    assert "GROUP BY" not in result.sql


def test_composite_pk_conditions_stay_inside_derived_query():
    where = generate(
        "count distinct orders per user where amount > 10",
        schema(primary_key=["tenant_id", "id"]),
    )
    whose = generate(
        "count distinct orders whose status is active",
        schema(primary_key=["tenant_id", "id"]),
    )

    assert where.success and whose.success
    assert "WHERE amount > 10 AND tenant_id IS NOT NULL AND id IS NOT NULL" in where.sql
    assert "GROUP BY user_id" in where.sql
    assert "WHERE status = 'active' AND tenant_id IS NOT NULL AND id IS NOT NULL" in whose.sql


def test_group_column_overlapping_identity_is_projected_once():
    result = generate(
        "count distinct orders per tenant_id",
        schema(primary_key=["tenant_id", "id"]),
    )

    assert result.success
    assert result.sql.count("tenant_id") == 4
    assert "SELECT DISTINCT tenant_id, id" in result.sql
    assert "GROUP BY tenant_id" in result.sql


def test_outer_ordering_and_limit():
    result = generate(
        "count distinct orders per user ordered by user_id desc limit 5",
        schema(primary_key=["tenant_id", "id"]),
    )

    assert result.success
    assert result.sql.index("GROUP BY user_id") < result.sql.index("ORDER BY user_id DESC")
    assert result.sql.index("ORDER BY user_id DESC") < result.sql.index("LIMIT 5")
    assert "ORDER BY" not in result.sql.split("FROM (", 1)[1].split(") AS", 1)[0]


def test_duplicate_rows_and_null_identity_are_handled_by_sqlite():
    result = generate("count distinct orders per user", schema(primary_key=["tenant_id", "id"]))
    assert result.success
    sql = result.sql.split("\n", 1)[1]
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER, amount INTEGER, status TEXT);"
        "INSERT INTO orders VALUES "
        "(1, 1, 10, 5, 'active'), (1, 1, 10, 6, 'active'), "
        "(1, 2, 10, 7, 'active'), (2, 1, 10, 8, 'active'), "
        "(NULL, 3, 10, 9, 'active'), (1, NULL, 10, 10, 'active');"
    )

    assert list(connection.execute(sql)) == [(10, 3)]


def test_duckdb_runtime_matches_sqlite_semantics():
    duckdb = pytest.importorskip("duckdb")
    result = generate("count distinct orders per user", schema(primary_key=["tenant_id", "id"]))
    assert result.success
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER, amount INTEGER, status VARCHAR)"
    )
    connection.execute(
        "INSERT INTO orders VALUES "
        "(1, 1, 10, 5, 'active'), (1, 1, 10, 6, 'active'), "
        "(1, 2, 10, 7, 'active'), (2, 1, 10, 8, 'active'), "
        "(NULL, 3, 10, 9, 'active'), (1, NULL, 10, 10, 'active')"
    )

    assert connection.execute(result.sql.split("\n", 1)[1]).fetchall() == [(10, 3)]
    connection.close()


@pytest.mark.parametrize("primary_key", [None, [], ["tenant_id", "missing"]])
def test_missing_or_invalid_identity_fails_closed(primary_key):
    context = schema(primary_key=primary_key)
    result = generate("count distinct orders per user", context)

    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "count distinct orders joined with users",
    "count distinct users joined on orders.user_id = users.id",
    "count distinct users who have products",
    "count distinct orders and average amount",
    "show distinct orders and count unique orders",
])
def test_relationships_paths_non_count_and_distinct_fail_closed(text):
    context = schema(primary_key=["tenant_id", "id"], include_products=True)
    result = generate(text, context)

    assert result.success is False
    assert result.sql is None


def test_single_pk_path_is_unchanged():
    result = generate("count distinct orders per user", schema(primary_key=["id"]))

    assert result.success
    assert "SELECT user_id, COUNT(DISTINCT id) AS count" in result.sql
    assert "_distinct_targets" not in result.sql


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_composite_derived_count_is_parseable_in_all_dialects(dialect):
    result = generate(
        "count distinct orders per user",
        schema(primary_key=["tenant_id", "id"]),
        dialect=dialect,
    )

    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_no_schema_legacy_output_is_unchanged():
    result = generate("count distinct orders per user")

    assert result.success
    assert result.schema_used is False
    assert result.sql == (
        "-- Generated for POSTGRES\n"
        "SELECT DISTINCT user_id, COUNT(*) AS count\n"
        "FROM orders\n"
        "INNER JOIN users ON orders.user_id = users.id\n"
        "GROUP BY user_id\n"
        "ORDER BY count DESC"
    )


def test_composite_generation_is_deterministic():
    context = schema(primary_key=["tenant_id", "id"])
    first = generate("count distinct orders per user where amount > 10", context)
    second = generate("count distinct orders per user where amount > 10", context)

    assert first.success and second.success
    assert first.sql == second.sql
    assert first.explanation == second.explanation
