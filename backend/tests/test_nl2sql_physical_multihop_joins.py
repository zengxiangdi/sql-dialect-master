"""Explicit physical INNER join chain contracts."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.tests.test_nl2sql_three_hop_path import schema


DIALECTS = ["mysql", "postgres", "oracle", "tsql", "hive", "spark", "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb"]


def generate(text, context=None, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=context)


@pytest.mark.parametrize("text,joins", [
    ("show user status joined with orders joined with shipments", ["JOIN orders", "JOIN shipments"]),
    ("show user status joined with orders joined with shipments joined with products", ["JOIN orders", "JOIN shipments", "JOIN products"]),
])
def test_inner_chain_renders_ordered_relationships(text, joins):
    result = generate(text, schema())
    assert result.success, result.explanation
    assert all(fragment in result.sql for fragment in joins)
    assert "LEFT JOIN" not in result.sql and "RIGHT JOIN" not in result.sql


def test_chain_reverses_relationship_pairs_and_validates_composite_edges():
    result = generate(
        "show user status joined with orders joined with shipments",
        schema(),
    )
    assert result.success
    assert "users.tenant_id = orders.tenant_id" in result.sql
    assert "orders.id = shipments.order_id" in result.sql


@pytest.mark.parametrize("text", [
    "users joined with orders and shipments",
    "users and orders joined with shipments",
    "users joined on orders.user_id = users.id joined with shipments",
    "users joined with orders joined on orders.id = shipments.order_id",
    "users joined with orders left joined with shipments",
    "users joined with orders natural join shipments",
    "users joined with orders cross join shipments",
    "users joined with orders joined with shipments joined with products joined with archives",
])
def test_invalid_chain_forms_fail_closed(text):
    result = generate(text, schema())
    assert result.success is False
    assert result.sql is None


def test_chain_select_star_fails_but_direct_star_remains_legacy():
    chain = generate("users joined with orders joined with shipments", schema())
    direct = generate("users joined with orders", schema())
    assert chain.success is False
    assert direct.success
    assert "SELECT *" in direct.sql


@pytest.mark.parametrize("text", [
    "show user status joined with orders joined with shipments where users.status = 'active'",
    "show user status joined with orders joined with shipments whose users.status is active",
])
def test_chain_allows_base_owned_filters(text):
    result = generate(text, schema())
    assert result.success
    assert "users.status = 'active'" in result.sql


@pytest.mark.parametrize("text", [
    "show user status joined with orders joined with shipments where orders.status = 'paid'",
    "show user status joined with orders joined with shipments whose orders.status is paid",
    "show user status joined with orders joined with shipments where status = 'paid'",
])
def test_chain_rejects_joined_owned_or_ambiguous_filters(text):
    result = generate(text, schema())
    assert result.success is False
    assert result.sql is None


def test_chain_base_group_aggregate_order_limit():
    result = generate(
        "show users.id and count joined with orders joined with shipments "
        "group by users.id order by users.id desc limit 5",
        schema(),
    )
    assert result.success
    assert "GROUP BY users.id" in result.sql
    assert "ORDER BY users.id DESC" in result.sql
    assert result.sql.endswith("LIMIT 5")


def test_chain_fanout_runtime_sqlite():
    result = generate("show user status joined with orders joined with shipments", schema())
    assert result.success
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE users(tenant_id INTEGER,id INTEGER,status TEXT);"
        "CREATE TABLE orders(tenant_id INTEGER,id INTEGER,user_id INTEGER,status TEXT);"
        "CREATE TABLE shipments(tenant_id INTEGER,id INTEGER,order_id INTEGER,product_id INTEGER,region TEXT);"
        "INSERT INTO users VALUES (1,1,'active');"
        "INSERT INTO orders VALUES (1,10,1,'paid'),(1,11,1,'paid');"
        "INSERT INTO shipments VALUES (1,100,10,20,'east'),(1,101,10,21,'east'),(1,102,11,20,'east');"
    )
    rows = connection.execute(result.sql.split("\n", 1)[1]).fetchall()
    assert len(rows) == 3


@pytest.mark.parametrize("dialect", DIALECTS)
def test_chain_parseability(dialect):
    result = generate(
        "show user status joined with orders joined with shipments",
        schema(), dialect,
    )
    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_chain_does_not_mix_unique_or_exists_paths():
    for text in [
        "count distinct products per user joined with orders joined with shipments",
        "users who have orders joined with shipments",
        "count distinct products per user including zero joined with orders joined with shipments",
    ]:
        result = generate(text, schema())
        assert result.success is False


def test_chain_with_table_hint_conflict_fails():
    result = NL2SQLGenerator().generate(
        "show user status joined with orders joined with shipments",
        "postgres",
        table_hint="orders",
        schema=schema(),
    )
    assert result.success is False


def test_chain_is_deterministic_and_no_schema_unchanged():
    text = "show user status joined with orders joined with shipments"
    first, second = generate(text, schema()), generate(text, schema())
    assert first.success and second.success
    assert first.sql == second.sql and first.explanation == second.explanation
    legacy = generate("users joined with orders")
    assert legacy.schema_used is False and legacy.success
