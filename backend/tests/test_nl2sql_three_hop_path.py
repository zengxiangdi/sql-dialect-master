"""Three-hop schema-aware unique target count contracts."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_pipeline.ir import PathDistinctCountPlan, PathStep, build_ir
from backend.core.nl2sql_pipeline.renderer import render_sql
from backend.core.nl2sql_schema import SchemaContext
from backend.tests.test_nl2sql_path_filter_ownership import twohop_schema


DIALECTS = [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
]


def schema(*, complete=True, with_archive=False):
    tables = [
        {"name": "users", "columns": [{"name": "tenant_id"}, {"name": "id"}, {"name": "status"}], "primary_key": ["tenant_id", "id"]},
        {"name": "orders", "columns": [{"name": "tenant_id"}, {"name": "id"}, {"name": "user_id"}, {"name": "status"}], "primary_key": ["id"]},
        {"name": "shipments", "columns": [{"name": "tenant_id"}, {"name": "id"}, {"name": "order_id"}, {"name": "product_id"}, {"name": "region"}], "primary_key": ["id"]},
        {"name": "products", "columns": [{"name": "tenant_id"}, {"name": "id"}, {"name": "status"}], "primary_key": ["tenant_id", "id"]},
    ]
    relationships = [
        {"from_table": "users", "to_table": "orders", "columns": [{"from_column": "tenant_id", "to_column": "tenant_id"}, {"from_column": "id", "to_column": "user_id"}]},
        {"from_table": "orders", "to_table": "shipments", "columns": [{"from_column": "tenant_id", "to_column": "tenant_id"}, {"from_column": "id", "to_column": "order_id"}]},
        {"from_table": "shipments", "to_table": "products", "columns": [{"from_column": "tenant_id", "to_column": "tenant_id"}, {"from_column": "product_id", "to_column": "id"}]},
    ]
    if not complete:
        relationships[2] = {"from_table": "shipments", "from_column": "product_id", "to_table": "products", "to_column": "id"}
    if with_archive:
        tables.append({"name": "archives", "columns": [{"name": "id"}, {"name": "product_id"}], "primary_key": ["id"]})
        relationships.append({"from_table": "products", "from_column": "id", "to_table": "archives", "to_column": "product_id"})
    return SchemaContext.from_mapping({"tables": tables, "relationships": relationships})


def generate(text, context=None, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=context)


def test_three_hop_nonzero_sql_shape():
    result = generate("count distinct products per user", schema())
    assert result.success
    assert result.sql.count("\n    JOIN ") == 3
    assert "products.tenant_id AS _target_0" in result.sql
    assert "GROUP BY _group_0, _group_1" in result.sql


def test_three_hop_zero_has_subject_baseline_and_three_joins():
    result = generate("count distinct products per user including zero", schema())
    assert result.success
    baseline, counts = result.sql.split(") AS b\nLEFT JOIN (", 1)
    assert "FROM users" in baseline
    assert "JOIN orders" in counts and "JOIN shipments" in counts and "JOIN products" in counts
    assert "WHERE" not in result.sql.rsplit(") AS c ON", 1)[1]
    assert "COALESCE(c.count, 0) AS count" in result.sql


def test_three_hop_all_endpoint_filters_are_subject_first_and_path_after():
    result = generate(
        "count distinct products per user whose users.status is active "
        "and orders.status is paid and shipments.region is east "
        "and products.status is enabled",
        schema(),
    )
    assert result.success
    where = result.sql.split("WHERE ", 1)[1]
    assert where.index("users.status") < where.index("orders.status") < where.index("shipments.region") < where.index("products.status")


def test_three_hop_four_predicates_are_allowed():
    result = generate(
        "count distinct products per user whose users.status is active "
        "and orders.status is paid and shipments.region is east and products.status is enabled",
        schema(),
    )
    assert result.success
    assert "条件: 4个" in result.explanation


def test_three_hop_five_predicates_fail_closed():
    result = generate(
        "count distinct products per user whose users.status is active "
        "and orders.status is paid and shipments.region is east "
        "and products.status is enabled and users.id > 0",
        schema(),
    )
    assert result.success is False


@pytest.mark.parametrize("text", [
    "count distinct products per user whose users.status is active and orders.status is paid and products.status is enabled and products.id > 0",
    "count distinct products per user whose users.status is active and orders.status is paid and products.status is enabled and users.id > 0",
])
def test_twohop_four_predicates_still_fail_closed(text):
    assert generate(text, twohop_schema()).success is False


def test_three_hop_multi_whose_zero_keeps_path_filters_out_of_baseline():
    result = generate(
        "count distinct products per user whose users.status is active "
        "and shipments.region is east and products.status is enabled including zero",
        schema(),
    )
    assert result.success
    baseline, counts = result.sql.split(") AS b\nLEFT JOIN (", 1)
    assert "users.status = 'active'" in baseline
    assert "shipments.region" not in baseline and "products.status" not in baseline
    assert "shipments.region = 'east'" in counts and "products.status = 'enabled'" in counts


def test_three_hop_composite_edge_incomplete_fails():
    result = generate("count distinct products per user", schema(complete=False))
    assert result.success is False


def test_four_hop_target_does_not_truncate_to_three():
    result = generate("count distinct archives per user", schema(with_archive=True))
    assert result.success is False
    assert result.sql is None


def test_four_step_direct_renderer_fails_closed():
    steps = tuple(
        PathStep(f"t{i}", f"t{i+1}", (("id", "id"),))
        for i in range(4)
    )
    plan = PathDistinctCountPlan("t0", steps, ("id",), ("id",))
    ir = build_ir("SELECT", "t0", ["*"], [], [], [], None, None, [], False, "postgres", path_distinct_count_plan=plan)
    sql, _, confidence, _ = render_sql(ir)
    assert sql is None and confidence == 0.0


def test_three_hop_duplicate_tenants_and_null_identity_runtime_sqlite():
    result = generate("count distinct products per user", schema())
    assert result.success
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE users(tenant_id INTEGER,id INTEGER,status TEXT);"
        "CREATE TABLE orders(tenant_id INTEGER,id INTEGER,user_id INTEGER,status TEXT);"
        "CREATE TABLE shipments(tenant_id INTEGER,id INTEGER,order_id INTEGER,product_id INTEGER,region TEXT);"
        "CREATE TABLE products(tenant_id INTEGER,id INTEGER,status TEXT);"
        "INSERT INTO users VALUES (1,1,'active'),(1,2,'active'),(2,1,'active');"
        "INSERT INTO orders VALUES (1,10,1,'paid'),(1,11,1,'paid'),(2,20,1,'paid');"
        "INSERT INTO shipments VALUES (1,100,10,10,'east'),(1,101,11,10,'east'),(2,200,20,10,'east');"
        "INSERT INTO products VALUES (1,10,'enabled'),(2,10,'enabled'),(NULL,60,'enabled');"
    )
    assert sorted(connection.execute(result.sql.split("\n", 1)[1]).fetchall()) == [
        (1, 1, 1), (2, 1, 1),
    ]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_three_hop_parseability(dialect):
    result = generate("count distinct products per user ordered by count desc limit 5", schema(), dialect)
    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_three_hop_generation_is_deterministic():
    text = "count distinct products per user whose shipments.region is east including zero ordered by count desc limit 5"
    first, second = generate(text, schema()), generate(text, schema())
    assert first.success and second.success
    assert first.sql == second.sql
    assert first.explanation == second.explanation
    assert first.evidence == second.evidence


def test_no_schema_unchanged():
    result = generate("count distinct products per user")
    assert result.schema_used is False and result.success

