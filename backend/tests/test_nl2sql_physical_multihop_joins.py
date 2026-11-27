"""Explicit physical INNER join chain contracts."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext
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


@pytest.mark.parametrize("predicate,expected", [
    ("users.status='active'", "users.status = 'active'"),
    ("users.status is null", "users.status IS NULL"),
    ("users.status is not null", "users.status IS NOT NULL"),
    (
        "users.status is not null and users.id > 0",
        "users.status IS NOT NULL AND users.id > 0",
    ),
    ("users.status='active' and users.id>0", "users.status = 'active' AND users.id > 0"),
    ("users.id>0 and users.status='active'", "users.id > 0 AND users.status = 'active'"),
    (
        "users.status='active' and users.status!='paid'",
        "users.status = 'active' AND users.status != 'paid'",
    ),
])
def test_chain_where_predicates_map_to_their_own_columns(predicate, expected):
    result = generate(
        "show users.status joined with orders joined with shipments where " + predicate,
        schema(),
    )

    assert result.success, result.explanation
    assert result.sql.split("WHERE ", 1)[1] == expected


@pytest.mark.parametrize("condition,expected", [
    ("status IS NULL", "users.status IS NULL"),
    ("status IS NOT NULL AND id > 0", "users.status IS NOT NULL AND users.id > 0"),
    ("users.status IS NOT NULL", "users.status IS NOT NULL"),
    ("status = 'active'", "users.status = 'active'"),
    (
        "unknown = 1 AND status = 'status IS NOT NULL' /* id > 0 */",
        "unknown = 1 AND users.status = 'status IS NOT NULL' /* id > 0 */",
    ),
    (
        "status = 'IS NOT NULL AND OR IN LIKE BETWEEN TRUE FALSE' -- status = 'active'",
        "users.status = 'IS NOT NULL AND OR IN LIKE BETWEEN TRUE FALSE' -- status = 'active'",
    ),
])
def test_chain_condition_qualification_only_changes_real_unquoted_columns(condition, expected):
    users = schema().table_candidates("users")[0]

    assert NL2SQLGenerator._schema_qualify_base_condition(condition, users) == expected


@pytest.mark.parametrize("predicate", [
    "status='paid'",
    "status='paid' and users.id>0",
    "users.status='active' and status='paid'",
    "status='paid' and users.status='active'",
    "status='paid' and users.status='active' and users.id>0",
    "users.id>0 and status='paid' and users.status='active'",
    "status='users.status' and users.id>0",
    "orders.status='paid' and users.status='active'",
])
def test_chain_where_cannot_borrow_another_predicate_qualifier(predicate):
    result = generate(
        "show users.status joined with orders joined with shipments where " + predicate,
        schema(),
    )

    assert result.success is False
    assert result.sql is None


def test_chain_base_only_unqualified_where_column_remains_allowed():
    context = schema()
    context = SchemaContext.from_mapping({
        "tables": [
            {
                "name": table.name,
                "columns": [{"name": column} for column in sorted(table.columns)]
                + ([{"name": "nickname"}] if table.name == "users" else []),
                "primary_key": list(table.primary_key),
            }
            for table in context.tables
        ],
        "relationships": [
            {
                "from_table": edge.from_table,
                "to_table": edge.to_table,
                "columns": [
                    {"from_column": left, "to_column": right}
                    for left, right in edge.column_pairs
                ],
            }
            for edge in context.relationships
        ],
    })
    result = generate(
        "show users.status joined with orders joined with shipments "
        "where nickname='bob' and users.id>0",
        context,
    )

    assert result.success, result.explanation
    assert "WHERE users.nickname = 'bob' AND users.id > 0" in result.sql


@pytest.mark.parametrize("literal", ["and, users.status = active", "x，y and users.id > 0"])
def test_chain_where_segment_mapping_preserves_literal_connectors(literal):
    result = generate(
        "show users.status joined with orders joined with shipments "
        f"where users.status='{literal}' and users.id>0",
        schema(),
    )

    assert result.success, result.explanation
    assert f"WHERE users.status = '{literal}' AND users.id > 0" in result.sql


@pytest.mark.parametrize("predicates", [
    "users.status='active' and",
    "users.status='active' and users.id>0 users.status='paid'",
    "users.status='active' users.status='paid'",
    "users.status='active' or users.status='paid'",
])
def test_chain_unmappable_where_segments_fail_closed(predicates):
    result = generate(
        "show users.status joined with orders joined with shipments where " + predicates,
        schema(),
    )

    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("extracted", [[], ["status = 'active'", "id > 0"], ["id = 'active'"]])
def test_chain_where_extraction_count_or_column_mismatch_fails_closed(monkeypatch, extracted):
    generator = NL2SQLGenerator()
    monkeypatch.setattr(generator, "_extract_conditions_enhanced", lambda *_: extracted)
    result = generator.generate(
        "show users.status joined with orders joined with shipments where users.status='active'",
        "postgres",
        schema=schema(),
    )

    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "show user status joined with orders joined with shipments with products",
    "show user status joined with orders joined with shipments who have products",
    "show user status joined with orders joined with shipments and products",
    "show user status joined with orders joined with shipments products",
    "show user status joined with orders joined with shipments join products",
])
def test_chain_tail_extra_tables_and_exists_fail_closed(text):
    result = generate(text, schema())
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("literal", [
    "'status = x'", "'x = y'", "'where status = x'", "'distinct'",
    "'limit 5'", "'order by users.id desc'", "'group by users.id'",
])
def test_chain_condition_qualification_preserves_literals(literal):
    result = generate(
        f"show user status joined with orders joined with shipments "
        f"where users.status = {literal}",
        schema(),
    )
    assert result.success
    assert f"users.status = {literal}" in result.sql
    assert literal.count("status") == literal.count("status")


@pytest.mark.parametrize("text", [
    "show user status joined with orders joined with shipments where status = 'paid'",
    "show user status joined with orders joined with shipments group by status",
    "show user status joined with orders joined with shipments order by status",
    "show user status joined with orders joined with shipments whose status is active",
])
def test_chain_unqualified_shared_columns_fail_closed(text):
    result = generate(text, schema())
    assert result.success is False


def test_chain_base_qualified_group_and_order_are_allowed():
    result = generate(
        "show user status joined with orders joined with shipments "
        "group by users.status order by users.status",
        schema(),
    )
    assert result.success
    assert "GROUP BY users.status" in result.sql
    assert "ORDER BY users.status" in result.sql


def test_chain_joined_qualified_projection_is_canonicalized():
    result = generate(
        "show users.status and orders.status joined with orders joined with shipments",
        schema(),
    )

    assert result.success
    assert "SELECT users.status, orders.status" in result.sql


def test_chain_joined_qualified_filter_is_owned():
    result = generate(
        "show users.status joined with orders joined with shipments where orders.status = 'paid'",
        schema(),
    )

    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "show users.status joined with orders joined with shipments group by orders.status",
    "show users.status joined with orders joined with shipments order by orders.status desc",
])
def test_chain_joined_group_and_order_are_fail_closed_until_ownership_completion(text):
    result = generate(text, schema())
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "show users.status joined with orders joined with shipments where orders.status in ('paid', 'pending')",
    "show users.status joined with orders joined with shipments where shipments.region like 'east%'",
    "show users.status joined with orders joined with shipments where orders.id between 1 and 10",
])
def test_chain_joined_complex_predicates_remain_fail_closed(text):
    result = generate(text, schema())
    assert result.success is False
    assert result.sql is None


def test_chain_or_predicate_fails_closed():
    result = generate(
        "show users.status joined with orders joined with shipments where users.status = 'active' or users.status = 'pending'",
        schema(),
    )
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "show count(distinct users.id) joined with orders joined with shipments",
    "count distinct orders per user joined with orders joined with shipments",
])
def test_chain_unique_count_conflicts_fail_closed(text):
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


@pytest.mark.parametrize("function", ["sum", "avg", "min", "max"])
def test_chain_base_qualified_aggregates_are_qualified(function):
    result = generate(
        f"show {function}(users.id) joined with orders joined with shipments",
        schema(),
    )
    assert result.success
    assert f"{function.upper()}(users.id)" in result.sql


@pytest.mark.parametrize("text", [
    "show sum(id) joined with orders joined with shipments",
    "show sum(orders.id) joined with orders joined with shipments",
    "show avg(orders.id) joined with orders joined with shipments",
])
def test_chain_aggregate_ownership_fail_closed(text):
    result = generate(text, schema())
    assert result.success is False
    assert result.sql is None


def test_chain_count_aggregate_regression():
    result = generate("show count(users.id) joined with orders joined with shipments", schema())
    assert result.success
    assert "COUNT(users.id) AS count" in result.sql


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
