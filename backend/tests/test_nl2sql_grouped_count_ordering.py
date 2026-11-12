"""Schema grouped unique count ordering contracts."""
import sqlite3
import pytest
import sqlglot
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_pipeline.ir import AggregateOrderingTerm, build_ir
from backend.core.nl2sql_pipeline.renderer import render_sql
from backend.tests.test_nl2sql_unique_count import make_schema
from backend.tests.test_nl2sql_composite_unique_count import schema as composite_schema

DIALECTS = ["mysql", "postgres", "oracle", "tsql", "hive", "spark", "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb"]

def generate(text, schema, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema)

@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_flat_count_ordering(direction):
    result = generate(f"count distinct orders per user ordered by count {direction}", make_schema(primary_key=["id"]))
    assert result.success and f"COUNT(DISTINCT id) {direction.upper()}" in result.sql

def test_flat_mixed_ordering_and_limit():
    result = generate("count distinct orders per user ordered by user_id desc, count asc limit 5", make_schema(primary_key=["id"]))
    assert result.success and "ORDER BY user_id DESC, COUNT(DISTINCT id) ASC" in result.sql and result.sql.endswith("LIMIT 5")

@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_composite_count_ordering(direction):
    result = generate(f"count distinct orders per user ordered by count {direction}", composite_schema(primary_key=["tenant_id", "id"]))
    assert result.success and f"COUNT(*) {direction.upper()}" in result.sql

@pytest.mark.parametrize("text", [
    "count distinct orders ordered by count desc",
    "count distinct orders top 10 ordered by count desc",
    "count distinct orders per user top 10",
    "count distinct orders per user top 10 ordered by user_id desc",
    "count distinct orders per user ordered by amount",
    "count distinct orders per user ordered by lower(user_id)",
    "count distinct orders per user ordered by count, count",
])
def test_grouped_count_ordering_fail_closed(text):
    result = generate(text, make_schema(primary_key=["id"]))
    assert result.success is False

def test_top_with_count_is_supported():
    result = generate("count distinct orders per user top 10 ordered by count desc", make_schema(primary_key=["id"]))
    assert result.success and result.sql.endswith("LIMIT 10")

def test_count_column_requires_qualification_for_group():
    schema = make_schema(primary_key=["id"])
    result = generate("count distinct orders per count ordered by count desc", schema)
    assert result.success is False

@pytest.mark.parametrize("dialect", DIALECTS)
def test_flat_count_ordering_parseable(dialect):
    result = generate("count distinct orders per user ordered by count desc limit 5", make_schema(primary_key=["id"]), dialect)
    assert result.success and sqlglot.parse_one(result.sql, read=dialect) is not None

def test_no_schema_is_unchanged():
    result = NL2SQLGenerator().generate("count distinct orders per user ordered by count desc", "postgres")
    assert result.schema_used is False and result.success


SCALAR_FILTER_VALUES = [
    "'limit 5'", "'top 10'", "'first 5'", "'前5'", "'5条'",
    "'5个'", "'5行'", "'5 rows'", "'only 5'", "'desc'", "'max'",
    "'order by count desc'", "'sort'", "'sorted'",
]


@pytest.mark.parametrize("value", SCALAR_FILTER_VALUES)
@pytest.mark.parametrize("primary_key", [["id"], ["tenant_id", "id"]])
def test_scalar_filter_words_do_not_create_order_or_limit(value, primary_key):
    schema = make_schema(primary_key=primary_key) if primary_key == ["id"] else composite_schema(primary_key=primary_key)
    result = generate(f"count distinct orders whose status is {value}", schema)

    assert result.success
    assert "WHERE status =" in result.sql
    assert "ORDER BY" not in result.sql
    assert "LIMIT" not in result.sql


@pytest.mark.parametrize("value", ["'top 10'", "'limit 5'", "'first 5'", "'5 rows'"])
def test_scalar_filter_word_with_real_limit_keeps_real_limit(value):
    result = generate(
        f"count distinct orders whose status is {value} limit 2",
        make_schema(primary_key=["id"]),
    )

    assert result.success
    assert result.sql.endswith("LIMIT 2")


@pytest.mark.parametrize("value", ["'top 10'", "'limit 5'"])
def test_scalar_real_top_or_ordering_remains_fail_closed(value):
    top = generate(
        f"count distinct orders top 10 whose status is {value}",
        make_schema(primary_key=["id"]),
    )
    ordered = generate(
        f"count distinct orders whose status is {value} ordered by count desc",
        make_schema(primary_key=["id"]),
    )

    assert top.success is False
    assert ordered.success is False


@pytest.mark.parametrize("value", ["'top 10'", "'limit 5'", "'first 5'", "'5 rows'", "'desc'", "'max'", "'order by count desc'"])
def test_grouped_flat_filter_words_do_not_create_order_or_limit(value):
    result = generate(
        f"count distinct orders per user whose status is {value}",
        make_schema(primary_key=["id"]),
    )

    assert result.success
    assert "WHERE status =" in result.sql
    assert "ORDER BY" not in result.sql
    assert "LIMIT" not in result.sql


@pytest.mark.parametrize("value", ["'top 10'", "'limit 5'"])
@pytest.mark.parametrize("schema", [make_schema(primary_key=["id"]), composite_schema(primary_key=["tenant_id", "id"])])
def test_grouped_filter_words_and_real_count_ordering(value, schema):
    result = generate(
        f"count distinct orders per user whose status is {value} ordered by count desc",
        schema,
    )

    assert result.success
    assert "ORDER BY" in result.sql
    assert "LIMIT" not in result.sql


@pytest.mark.parametrize("text,expected", [
    ("count distinct orders per user ordered by count desc top 10", "LIMIT 10"),
    ("count distinct orders per user top 10 ordered by count desc", "LIMIT 10"),
    ("count distinct orders per user ordered by count desc, user_id asc top 10", "LIMIT 10"),
])
def test_flat_top_position_with_count_ordering(text, expected):
    result = generate(text, make_schema(primary_key=["id"]))

    assert result.success
    assert result.sql.endswith(expected)


@pytest.mark.parametrize("text", [
    "count distinct orders per user ordered by user_id desc top 5",
    "count distinct orders per user top 10 ordered by user_id desc",
    "count distinct orders per user top 10",
])
def test_flat_top_without_count_ordering_fails_closed(text):
    result = generate(text, make_schema(primary_key=["id"]))

    assert result.success is False


def test_flat_group_ordering_limit_regression():
    result = generate(
        "count distinct orders per user ordered by user_id desc limit 5",
        make_schema(primary_key=["id"]),
    )

    assert result.success
    assert "ORDER BY user_id DESC" in result.sql
    assert result.sql.endswith("LIMIT 5")


def test_composite_group_ordering_limit_regression():
    result = generate(
        "count distinct orders per user ordered by user_id desc limit 5",
        composite_schema(primary_key=["tenant_id", "id"]),
    )

    assert result.success
    assert "ORDER BY user_id DESC" in result.sql
    assert result.sql.endswith("LIMIT 5")


def test_flat_count_ordering_runtime_sqlite():
    result = generate(
        "count distinct orders per user ordered by count desc limit 2",
        make_schema(primary_key=["id"]),
    )
    assert result.success
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE orders(id INTEGER, user_id INTEGER, amount INTEGER, status TEXT);"
        "INSERT INTO orders VALUES (1, 10, 1, 'active'), (2, 10, 1, 'active'), (3, 20, 1, 'active'), (4, 30, 1, 'active');"
    )

    assert connection.execute(result.sql.split("\n", 1)[1]).fetchall() == [
        (10, 2), (20, 1),
    ]


def test_composite_count_ordering_runtime_sqlite():
    result = generate(
        "count distinct orders per user ordered by count desc limit 2",
        composite_schema(primary_key=["tenant_id", "id"]),
    )
    assert result.success
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER, amount INTEGER, status TEXT);"
        "INSERT INTO orders VALUES "
        "(1, 1, 10, 1, 'active'), (1, 2, 10, 1, 'active'), "
        "(1, 3, 20, 1, 'active'), (2, 1, 30, 1, 'active');"
    )

    assert connection.execute(result.sql.split("\n", 1)[1]).fetchall() == [
        (10, 2), (20, 1),
    ]


@pytest.mark.parametrize("aggregations", [
    [], ["AVG(amount) AS count"], ["COUNT(DISTINCT id) AS cnt"],
    ["COUNT(DISTINCT id) AS count", "SUM(amount) AS total"],
])
def test_flat_renderer_validates_count_aggregation(aggregations):
    ir = build_ir(
        "SELECT", "orders", ["*"], [], aggregations, ["user_id"],
        None, None, [], False, "postgres",
        aggregate_orderings=(AggregateOrderingTerm("count", None, "DESC"),),
    )
    sql, _, confidence, _ = render_sql(ir)
    assert sql is None
    assert confidence == 0.0


def test_flat_renderer_accepts_valid_count_aggregation():
    ir = build_ir(
        "SELECT", "orders", ["*"], [], ["COUNT(DISTINCT id) AS count"], ["user_id"],
        None, None, [], False, "postgres",
        aggregate_orderings=(AggregateOrderingTerm("count", None, "DESC"),),
    )
    sql, _, confidence, _ = render_sql(ir)
    assert sql is not None
    assert "ORDER BY COUNT(DISTINCT id) DESC, user_id ASC" in sql
    assert confidence > 0
