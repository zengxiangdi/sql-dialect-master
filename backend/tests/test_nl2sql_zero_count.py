"""Explicit zero-count inclusion contracts for schema-aware unique targets."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


DIALECTS = [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
]


def make_schema(*, path_length=2):
    tables = [
        {
            "name": "users",
            "columns": [{"name": "tenant_id"}, {"name": "id"}, {"name": "status"}],
            "primary_key": ["tenant_id", "id"],
        },
        {
            "name": "orders",
            "columns": [
                {"name": "tenant_id"}, {"name": "id"},
                {"name": "user_id"}, {"name": "product_id"},
            ],
            "primary_key": ["id"],
        },
        {
            "name": "products",
            "columns": [{"name": "tenant_id"}, {"name": "id"}],
            "primary_key": ["tenant_id", "id"],
        },
    ]
    if path_length == 1:
        relationships = [{
            "from_table": "users",
            "to_table": "orders",
            "columns": [
                {"from_column": "tenant_id", "to_column": "tenant_id"},
                {"from_column": "id", "to_column": "user_id"},
            ],
        }]
    else:
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
    return SchemaContext.from_mapping({"tables": tables, "relationships": relationships})


def generate(text, schema=None, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema)


@pytest.mark.parametrize("text", [
    "count distinct products per user including zero",
    "count distinct products per user include zero",
    "count distinct products per user including users with no products",
    "count distinct products per user including those with no products",
    "count distinct products per user including users with zero products",
    "count distinct products per user with zero products",
    "count distinct products per user 含0",
    "count distinct products per user 含零",
    "每个用户的不同产品数，包括没有产品的用户",
    "每个用户的不同产品数，没有产品的用户也包括",
])
def test_explicit_zero_wording_uses_zero_count_baseline(text):
    result = generate(text, make_schema())

    assert result.success
    assert "LEFT JOIN" in result.sql
    assert "COALESCE(c.count, 0) AS count" in result.sql
    assert "AS b" in result.sql
    assert "AS c ON" in result.sql


def test_default_path_count_still_excludes_zero_subjects():
    result = generate("count distinct products per user", make_schema())

    assert result.success
    assert "LEFT JOIN" not in result.sql
    assert "COALESCE" not in result.sql
    assert "JOIN products" in result.sql


@pytest.mark.parametrize("text", [
    "count products per user including zero",
    "所有用户的产品数（含 0）",
    "count distinct products including zero",
    "count distinct products with zero products",
])
def test_zero_wording_without_unique_group_or_path_fails_closed(text):
    result = generate(text, make_schema())

    assert result.success is False
    assert result.sql is None


def test_zero_phrase_inside_quotes_or_comments_does_not_activate_mode():
    quoted = generate(
        "count distinct products per user whose status is 'including zero'",
        make_schema(),
    )
    commented = generate(
        "count distinct products per user /* including zero */",
        make_schema(),
    )

    assert quoted.success and commented.success
    assert "LEFT JOIN" not in quoted.sql
    assert "LEFT JOIN" not in commented.sql


def test_zero_count_subject_whose_is_applied_to_baseline_and_counts():
    result = generate(
        "count distinct products per user whose status is active including zero",
        make_schema(),
    )

    assert result.success
    assert result.sql.count("users.status = 'active'") == 2
    assert "users.status = 'active'" in result.sql.split("LEFT JOIN", 1)[0]
    assert "users.status = 'active'" in result.sql.split("LEFT JOIN", 1)[1]


@pytest.mark.parametrize("text", [
    "count distinct products per user where users.tenant_id = 1 including zero",
    "count distinct products per user whose tenant_id is 1 including zero",
    "count distinct products per user whose products.tenant_id is 1 including zero",
    "count distinct products per user whose orders.tenant_id is 1 including zero",
    "count distinct products per user ordered by tenant_id including zero",
])
def test_zero_count_ordinary_where_target_filters_and_order_fail_closed(text):
    result = generate(text, make_schema())

    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("path_length", [1, 2])
def test_zero_count_plan_supports_one_and_two_hop_paths(path_length):
    target = "orders" if path_length == 1 else "products"
    result = generate(
        f"count distinct {target} per user including zero",
        make_schema(path_length=path_length),
    )

    assert result.success
    assert "LEFT JOIN" in result.sql
    assert "COALESCE(c.count, 0)" in result.sql
    if path_length == 1:
        assert "JOIN orders ON users.tenant_id = orders.tenant_id AND users.id = orders.user_id" in result.sql
    else:
        assert "JOIN orders ON users.tenant_id = orders.tenant_id AND users.id = orders.user_id" in result.sql
        assert "JOIN products ON orders.tenant_id = products.tenant_id AND orders.product_id = products.id" in result.sql


def _insert_runtime_rows(connection):
    statements = (
        "CREATE TABLE users(tenant_id INTEGER, id INTEGER, status TEXT)",
        "CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER, product_id INTEGER)",
        "CREATE TABLE products(tenant_id INTEGER, id INTEGER)",
        "INSERT INTO users VALUES (1,1,'active'),(1,2,'active'),(2,1,'active'),(2,2,'inactive'),(NULL,7,'active')",
        "INSERT INTO orders VALUES (1,1,1,10),(1,2,1,10),(1,3,1,11),(1,4,2,10),(2,5,1,10),(NULL,6,1,10),(1,7,7,10)",
        "INSERT INTO products VALUES (1,10),(1,11),(2,10),(NULL,99)",
    )
    for statement in statements:
        connection.execute(statement)


def test_two_hop_zero_count_runtime_sqlite():
    result = generate("count distinct products per user including zero", make_schema())
    assert result.success
    connection = sqlite3.connect(":memory:")
    _insert_runtime_rows(connection)

    assert sorted(connection.execute(result.sql.split("\n", 1)[1]).fetchall()) == [
        (1, 1, 2), (1, 2, 1), (2, 1, 1), (2, 2, 0),
    ]


def test_two_hop_zero_count_runtime_duckdb():
    duckdb = pytest.importorskip("duckdb")
    result = generate("count distinct products per user including zero", make_schema())
    assert result.success
    connection = duckdb.connect()
    _insert_runtime_rows(connection)

    assert sorted(connection.execute(result.sql.split("\n", 1)[1]).fetchall()) == [
        (1, 1, 2), (1, 2, 1), (2, 1, 1), (2, 2, 0),
    ]
    connection.close()


def test_one_hop_zero_count_runtime_includes_users_without_orders():
    result = generate(
        "count distinct orders per user including zero",
        make_schema(path_length=1),
    )
    assert result.success
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE users(tenant_id INTEGER, id INTEGER);"
        "CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER);"
        "INSERT INTO users VALUES (1,1),(1,2),(2,1);"
        "INSERT INTO orders VALUES (1,10,1),(1,10,1),(2,11,1);"
    )

    assert sorted(connection.execute(result.sql.split("\n", 1)[1]).fetchall()) == [
        (1, 1, 1), (1, 2, 0), (2, 1, 1),
    ]


def test_zero_count_limit_is_outer_and_results_are_deterministic():
    text = "count distinct products per user whose status is active including zero limit 2"
    first = generate(text, make_schema())
    second = generate(text, make_schema())

    assert first.success and second.success
    assert first.sql == second.sql
    assert first.explanation == second.explanation
    assert first.sql.index(") AS c ON") < first.sql.index("LIMIT 2")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_zero_count_sql_is_parseable_in_all_dialects(dialect):
    result = generate(
        "count distinct products per user including zero limit 5",
        make_schema(),
        dialect=dialect,
    )

    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


@pytest.mark.parametrize("text", [
    "count distinct products per user including zero",
    "count distinct products per user",
    "count products per user including zero",
])
def test_no_schema_zero_phrasing_keeps_legacy_behavior(text):
    first = generate(text)
    second = generate(text)

    assert first.success == second.success
    assert first.sql == second.sql
    assert first.schema_used is False


def test_zero_wording_preserves_existing_no_schema_unique_count_output():
    plain = generate("count distinct products per user")
    zero = generate("count distinct products per user including zero")

    assert plain.success and zero.success
    assert zero.sql == plain.sql
