"""P1 Batch 2a schema-aware COUNT and single-column grouping contracts."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


SCHEMA = SchemaContext.from_mapping(
    {
        "tables": [
            {"name": "users", "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "name"}]},
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "amount"}, {"name": "status"}]},
        ],
        "relationships": [{
            "from_table": "orders", "from_column": "user_id",
            "to_table": "users", "to_column": "id",
        }],
    }
)


def generate(text: str, *, schema: bool = True):
    return NL2SQLGenerator().generate(
        text, "postgres", schema=SCHEMA if schema else None
    )


@pytest.mark.parametrize("text", [
    "Show number of orders",
    "Show count of orders",
    "Count orders",
    "How many orders",
])
def test_schema_count_only(text):
    result = generate(text)
    assert result.success
    assert "SELECT COUNT(*) AS count" in result.sql
    assert "GROUP BY" not in result.sql


@pytest.mark.parametrize("text", [
    "Show number of orders per user_id",
    "Show count of orders per user_id",
    "Count orders grouped by user_id",
    "Count orders by user_id",
])
def test_schema_count_group_by_user_id(text):
    result = generate(text)
    assert result.success
    assert "SELECT user_id, COUNT(*) AS count" in result.sql
    assert "GROUP BY user_id" in result.sql


@pytest.mark.parametrize("column", ["id", "amount"])
def test_schema_count_group_by_explicit_column(column):
    result = generate(f"Count orders by {column}")
    assert result.success
    assert f"SELECT {column}, COUNT(*) AS count" in result.sql
    assert f"GROUP BY {column}" in result.sql


@pytest.mark.parametrize("text", [
    "Show number of orders per unknown",
    "Show number of orders per user",
    "统计每个部门员工数量",
    "统计订单数量",
    "Count orders per user_id and status",
])
def test_schema_unresolved_or_multiple_group_columns_fail_closed(text):
    result = generate(text)
    assert result.success is False
    assert result.sql is None


def test_schema_group_by_without_aggregation_is_supported():
    result = generate("Show users group by name")
    assert result.success
    assert "SELECT name" in result.sql
    assert "GROUP BY name" in result.sql


def test_schema_order_by_is_not_reinterpreted_as_group_by():
    result = generate("Show users ordered by name")
    assert result.success
    assert "GROUP BY" not in result.sql
    assert "ORDER BY name ASC" in result.sql


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_schema_group_count_parses_in_all_dialects(dialect):
    result = NL2SQLGenerator().generate("Count orders by user_id", dialect, schema=SCHEMA)
    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


@pytest.mark.parametrize("text", [
    "Show number of orders",
    "Count orders by user_id",
    "统计订单数量",
    "Show users group by name",
])
def test_no_schema_outputs_remain_current(text):
    first = generate(text, schema=False)
    second = generate(text, schema=False)
    assert first.success == second.success
    assert first.sql == second.sql
    assert first.schema_used is False


def test_schema_group_results_are_deterministic():
    first = generate("Count orders by user_id")
    second = generate("Count orders by user_id")
    assert first.success and second.success
    assert first.sql == second.sql
