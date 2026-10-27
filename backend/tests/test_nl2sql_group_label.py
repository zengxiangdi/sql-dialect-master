"""P1 Batch 2b2 English group-label and subject-table contracts."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def schema_context(*, relationship=True, orders_user_id=True, employees_department=True, users=True):
    tables = [
        {"name": "orders", "columns": [{"name": "id"}, {"name": "amount"}]},
        {"name": "employees", "columns": [{"name": "id"}, {"name": "name"}]},
    ]
    if orders_user_id:
        tables[0]["columns"].append({"name": "user_id"})
    if employees_department:
        tables[1]["columns"].append({"name": "department"})
    if users:
        tables.append({"name": "users", "columns": [{"name": "id"}, {"name": "name"}]})
    relationships = []
    if relationship and users and orders_user_id:
        relationships.append({
            "from_table": "orders", "from_column": "user_id",
            "to_table": "users", "to_column": "id",
        })
    return SchemaContext.from_mapping({"tables": tables, "relationships": relationships})


def generate(text, schema=None):
    return NL2SQLGenerator().generate("".join([text]), "postgres", schema=schema)


@pytest.mark.parametrize("text", [
    "How many orders per user",
    "Show number of orders per user",
    "Count orders per user",
])
def test_orders_per_user_uses_data_fk_group(text):
    result = generate(text, schema_context())
    assert result.success
    assert "SELECT user_id, COUNT(*) AS count" in result.sql
    assert "FROM orders" in result.sql
    assert "GROUP BY user_id" in result.sql
    assert "JOIN users" not in result.sql


def test_orders_per_user_allows_unique_fk_without_relationship():
    result = generate("How many orders per user", schema_context(relationship=False))
    assert result.success
    assert "SELECT user_id, COUNT(*) AS count" in result.sql
    assert "GROUP BY user_id" in result.sql


def test_orders_per_user_uses_fk_when_relationship_is_declared_in_reverse():
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}]},
            {"name": "users", "columns": [{"name": "id"}]},
        ],
        "relationships": [
            {
                "from_table": "users",
                "from_column": "id",
                "to_table": "orders",
                "to_column": "user_id",
            },
        ],
    })
    result = generate("How many orders per user", schema)
    assert result.success
    assert "SELECT user_id, COUNT(*) AS count" in result.sql
    assert "FROM orders" in result.sql
    assert "GROUP BY user_id" in result.sql


@pytest.mark.parametrize("text", [
    "How many users per order",
    "Count users per order",
    "Show number of users per order",
])
def test_reverse_group_label_relationship_fails_closed(text):
    result = generate(text, schema_context())
    assert result.success is False
    assert result.sql is None


def test_employees_per_department_uses_subject_column():
    result = generate("Count employees per department", schema_context())
    assert result.success
    assert "SELECT department, COUNT(*) AS count" in result.sql
    assert "FROM employees" in result.sql
    assert "GROUP BY department" in result.sql


@pytest.mark.parametrize("schema", [
    schema_context(users=False),
    schema_context(orders_user_id=False),
])
def test_orders_per_user_without_label_table_or_fk_fails_closed(schema):
    result = generate("How many orders per user", schema)
    assert result.success is False
    assert result.sql is None


def test_orders_per_user_with_multiple_relationships_fails_closed():
    schema = schema_context()
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "buyer_id"}]},
            {"name": "users", "columns": [{"name": "id"}]},
        ],
        "relationships": [
            {"from_table": "orders", "from_column": "user_id", "to_table": "users", "to_column": "id"},
            {"from_table": "orders", "from_column": "buyer_id", "to_table": "users", "to_column": "id"},
        ],
    })
    result = generate("How many orders per user", schema)
    assert result.success is False
    assert result.sql is None


def test_employees_per_department_without_department_column_fails_closed():
    result = generate("Count employees per department", schema_context(employees_department=False))
    assert result.success is False
    assert result.sql is None


def test_orders_per_department_without_column_or_relationship_fails_closed():
    result = generate("Show number of orders per department", schema_context())
    assert result.success is False
    assert result.sql is None


def test_unknown_group_label_fails_closed():
    result = generate("How many orders per unknown", schema_context())
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "Show number of orders per user_id",
    "Count orders by user_id",
    "Count orders grouped by user_id",
])
def test_batch_two_a_explicit_columns_remain_unchanged(text):
    result = generate(text, schema_context())
    assert result.success
    assert "user_id" in result.sql
    assert "GROUP BY user_id" in result.sql


def test_count_only_and_ordering_do_not_gain_grouping():
    count = generate("Show number of orders", schema_context())
    ordered = generate("Show users ordered by name", schema_context())
    assert count.success and "COUNT(*) AS count" in count.sql and "GROUP BY" not in count.sql
    assert ordered.success and "GROUP BY" not in ordered.sql


@pytest.mark.parametrize("text", ["统计每个部门员工数量", "每个用户的订单数量"])
def test_chinese_group_labels_remain_batch_two_b_fail_closed(text):
    result = generate(text, schema_context())
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "How many orders per user",
    "Count employees per department",
    "Show number of orders per user_id",
])
def test_no_schema_outputs_remain_current(text):
    first = generate(text)
    second = generate(text)
    assert first.success == second.success
    assert first.sql == second.sql
    assert first.schema_used is False


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_group_label_sql_parses_in_all_dialects(dialect):
    result = NL2SQLGenerator().generate("How many orders per user", dialect, schema=schema_context())
    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_group_label_results_are_deterministic():
    first = generate("How many orders per user", schema_context())
    second = generate("How many orders per user", schema_context())
    assert first.success and second.success
    assert first.sql == second.sql
