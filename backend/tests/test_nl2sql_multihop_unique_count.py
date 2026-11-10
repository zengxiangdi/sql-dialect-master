"""Batch A two-hop schema-aware unique target count contracts."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def schema(*, complete_relationships=True, extra_relationships=None):
    tables = [
        {
            "name": "users",
            "columns": [{"name": "tenant_id"}, {"name": "id"}],
            "primary_key": ["tenant_id", "id"],
        },
        {
            "name": "orders",
            "columns": [
                {"name": "tenant_id"},
                {"name": "id"},
                {"name": "user_id"},
                {"name": "product_id"},
            ],
            "primary_key": ["id"],
        },
        {
            "name": "products",
            "columns": [{"name": "tenant_id"}, {"name": "id"}],
            "primary_key": ["tenant_id", "id"],
        },
    ]
    if complete_relationships:
        relationships = [
            {
                "from_table": "orders",
                "to_table": "users",
                "columns": [
                    {"from_column": "tenant_id", "to_column": "tenant_id"},
                    {"from_column": "user_id", "to_column": "id"},
                ],
            },
            {
                "from_table": "orders",
                "to_table": "products",
                "columns": [
                    {"from_column": "tenant_id", "to_column": "tenant_id"},
                    {"from_column": "product_id", "to_column": "id"},
                ],
            },
        ]
    else:
        relationships = [
            {
                "from_table": "orders",
                "from_column": "user_id",
                "to_table": "users",
                "to_column": "id",
            },
            {
                "from_table": "orders",
                "from_column": "product_id",
                "to_table": "products",
                "to_column": "id",
            },
        ]
    if extra_relationships:
        relationships.extend(extra_relationships)
    return SchemaContext.from_mapping({
        "tables": tables,
        "relationships": relationships,
    })


def generate(text, context=None, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=context)


def test_incomplete_composite_edges_fail_closed():
    result = generate("count distinct products per user", schema(complete_relationships=False))

    assert result.success is False
    assert result.sql is None


def test_complete_two_hop_path_renders_subject_and_target_identity():
    result = generate("count distinct products per user", schema())

    assert result.success
    assert "JOIN orders ON users.tenant_id = orders.tenant_id AND users.id = orders.user_id" in result.sql
    assert "JOIN products ON orders.tenant_id = products.tenant_id AND orders.product_id = products.id" in result.sql
    assert "users.tenant_id AS _group_0" in result.sql
    assert "users.id AS _group_1" in result.sql
    assert "products.tenant_id AS _target_0" in result.sql
    assert "products.id AS _target_1" in result.sql
    assert "GROUP BY _group_0, _group_1" in result.sql


def test_chinese_unique_wording_uses_the_same_path_plan():
    result = generate("每个用户的不同产品数", schema())

    assert result.success
    assert "COUNT(*) AS count" in result.sql
    assert "_distinct_targets" in result.sql


def test_subject_whose_is_inner_and_limit_is_outer():
    result = generate(
        "count distinct products per user whose tenant_id is 1 limit 5",
        schema(),
    )

    assert result.success
    assert "WHERE users.tenant_id = 1" in result.sql
    assert result.sql.index("WHERE users.tenant_id = 1") < result.sql.index(") AS _distinct_targets")
    assert result.sql.index(") AS _distinct_targets") < result.sql.index("LIMIT 5")


@pytest.mark.parametrize("text", [
    "count distinct products per user where users.tenant_id = 1",
    "count distinct products per user whose products.tenant_id is 1",
    "count distinct products per user whose orders.tenant_id is 1",
    "count distinct products per user ordered by tenant_id",
])
def test_non_batch_a_filters_and_ordering_fail_closed(text):
    result = generate(text, schema())

    assert result.success is False
    assert result.sql is None


def test_repeated_product_orders_count_once_and_tenants_remain_distinct():
    result = generate("count distinct products per user", schema())
    assert result.success
    sql = result.sql.split("\n", 1)[1]
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE users(tenant_id INTEGER, id INTEGER);"
        "CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER, product_id INTEGER);"
        "CREATE TABLE products(tenant_id INTEGER, id INTEGER);"
        "INSERT INTO users VALUES (1, 1), (1, 2), (2, 1);"
        "INSERT INTO orders VALUES "
        "(1, 1, 1, 10), (1, 2, 1, 10), (1, 3, 1, 11), "
        "(1, 4, 2, 10), (2, 5, 1, 10);"
        "INSERT INTO products VALUES (1, 10), (1, 11), (2, 10);"
    )

    assert list(connection.execute(sql)) == [(1, 1, 2), (1, 2, 1), (2, 1, 1)]


def test_three_hop_cycle_and_multiple_paths_fail_closed():
    three_hop = schema(extra_relationships=[
        {
            "from_table": "products",
            "from_column": "id",
            "to_table": "shipments",
            "to_column": "product_id",
        },
    ])
    # The missing shipments table makes the candidate invalid at schema resolution.
    assert not generate("count distinct shipments per user", three_hop).success

    multiple = schema(extra_relationships=[
        {
            "from_table": "users",
            "to_table": "products",
            "columns": [
                {"from_column": "tenant_id", "to_column": "tenant_id"},
                {"from_column": "id", "to_column": "id"},
            ],
        },
    ])
    assert not generate("count distinct products per user", multiple).success


def test_one_hop_unique_count_keeps_single_table_renderer():
    context = SchemaContext.from_mapping({
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
    })
    result = generate("count distinct orders per user", context)

    assert result.success
    assert "COUNT(DISTINCT id) AS count" in result.sql
    assert "_group_0" not in result.sql


def test_no_schema_remains_legacy():
    result = generate("count distinct products per user")

    assert result.success
    assert result.schema_used is False
    assert "SELECT DISTINCT user_id, COUNT(*) AS count" in result.sql


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_two_hop_unique_count_is_parseable_in_all_dialects(dialect):
    result = generate("count distinct products per user", schema(), dialect=dialect)

    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_two_hop_generation_is_deterministic():
    context = schema()
    first = generate("count distinct products per user whose tenant_id is 1 limit 5", context)
    second = generate("count distinct products per user whose tenant_id is 1 limit 5", context)

    assert first.success and second.success
    assert first.sql == second.sql
    assert first.explanation == second.explanation
