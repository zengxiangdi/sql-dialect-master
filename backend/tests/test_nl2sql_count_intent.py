"""P1 Batch 2b1 count-versus-quantity schema contracts."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


BASE = {
    "tables": [
        {"name": "orders", "columns": [{"name": "id"}, {"name": "amount"}, {"name": "user_id"}]},
        {"name": "products", "columns": [{"name": "id"}, {"name": "quantity"}]},
    ],
    "relationships": [],
}


def context(*, inventory_columns=None, orders_quantity=False):
    tables = [dict(table) for table in BASE["tables"]]
    if orders_quantity:
        tables[0] = {**tables[0], "columns": [*tables[0]["columns"], {"name": "quantity"}]}
    if inventory_columns is not None:
        tables.append({"name": "inventory", "columns": inventory_columns})
    return SchemaContext.from_mapping({"tables": tables, "relationships": []})


def single_table_context(name: str, columns: list[str]) -> SchemaContext:
    return SchemaContext.from_mapping({
        "tables": [{"name": name, "columns": [{"name": column} for column in columns]}],
        "relationships": [],
    })


def generate(text: str, schema: SchemaContext | None):
    return NL2SQLGenerator().generate(text, "postgres", schema=schema)


@pytest.mark.parametrize("text", [
    "统计订单数量", "订单数量", "统计订单数",
    "Show number of orders", "Count orders", "How many orders",
])
def test_schema_order_count_is_count_only(text):
    result = generate(text, context())
    assert result.success
    assert "SELECT COUNT(*) AS count" in result.sql
    assert "GROUP BY" not in result.sql


def test_orders_quantity_does_not_change_order_count():
    result = generate("统计订单数量", context(orders_quantity=True))
    assert result.success
    assert "COUNT(*) AS count" in result.sql
    assert "SUM(quantity)" not in result.sql


def test_products_quantity_does_not_turn_product_count_into_sum():
    result = generate("统计产品数量", context())
    assert result.success
    assert "FROM products" in result.sql
    assert "COUNT(*) AS count" in result.sql
    assert "SUM(quantity)" not in result.sql


@pytest.mark.parametrize("text,table", [
    ("订单数", "orders"),
    ("员工数", "employees"),
    ("用户数", "users"),
    ("产品数", "products"),
])
def test_entity_counter_suffix_is_count(text, table):
    result = generate(text, single_table_context(table, ["id"]))
    assert result.success
    assert f"FROM {table}" in result.sql
    assert "COUNT(*) AS count" in result.sql


@pytest.mark.parametrize("text", [
    "显示用户数据", "查看用户数据", "用户数据", "数据库", "数字", "数组", "参数", "函数", "分数",
])
def test_data_words_do_not_trigger_schema_count(text):
    result = generate(text, context())
    assert "COUNT(*) AS count" not in (result.sql or "")


def test_qualified_measure_tables_use_basename():
    inventory = SchemaContext.from_mapping({
        "tables": [{"name": "public.inventory", "columns": [{"name": "quantity"}]}],
        "relationships": [],
    })
    orders = SchemaContext.from_mapping({
        "tables": [{"name": "public.orders", "columns": [{"name": "quantity"}]}],
        "relationships": [],
    })
    inventory_result = generate("统计库存数量", inventory)
    orders_result = generate("统计购买数量", orders)
    assert inventory_result.success and "SUM(quantity)" in inventory_result.sql
    assert orders_result.success and "SUM(quantity)" in orders_result.sql


def test_inventory_quantity_is_sum_measure():
    result = generate(
        "统计库存数量",
        context(inventory_columns=[{"name": "id"}, {"name": "quantity"}]),
    )
    assert result.success
    assert "SELECT SUM(quantity)" in result.sql
    assert "FROM inventory" in result.sql
    assert "GROUP BY" not in result.sql


def test_purchase_quantity_is_sum_on_orders():
    result = generate("统计购买数量", context(orders_quantity=True))
    assert result.success
    assert "SELECT SUM(quantity)" in result.sql
    assert "FROM orders" in result.sql


@pytest.mark.parametrize(
    "schema,text",
    [
        (context(), "统计库存数量"),
        (context(inventory_columns=[{"name": "id"}]), "统计库存数量"),
    ],
)
def test_inventory_measure_without_inventory_quantity_fails_closed(schema, text):
    result = generate(text, schema)
    assert result.success is False
    assert result.sql is None


def test_order_count_without_orders_table_fails_closed():
    schema = SchemaContext.from_mapping({"tables": [{"name": "users", "columns": [{"name": "id"}]}]})
    result = generate("统计订单数量", schema)
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "统计每个部门员工数量",
    "每个用户的订单数量",
    "How many orders per user",
])
def test_batch_two_b_group_labels_remain_fail_closed(text):
    result = generate(text, context())
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_count_and_sum_parse_in_all_dialects(dialect):
    count = NL2SQLGenerator().generate("统计订单数量", dialect, schema=context())
    assert count.success
    assert sqlglot.parse_one(count.sql, read=dialect) is not None

    inventory = NL2SQLGenerator().generate(
        "统计库存数量",
        dialect,
        schema=context(inventory_columns=[{"name": "quantity"}]),
    )
    assert inventory.success
    assert sqlglot.parse_one(inventory.sql, read=dialect) is not None


@pytest.mark.parametrize("text", ["统计订单数量", "统计库存数量", "统计购买数量"])
def test_no_schema_count_outputs_remain_current(text):
    first = generate(text, None)
    second = generate(text, None)
    assert first.success == second.success
    assert first.sql == second.sql
    assert first.schema_used is False


def test_no_schema_order_count_keeps_legacy_quantity_grouping():
    result = generate("统计订单数量", None)
    assert result.success
    assert "COUNT(*) AS count" in result.sql
    assert "GROUP BY quantity" in result.sql


def test_count_results_are_deterministic():
    first = generate("统计订单数量", context())
    second = generate("统计订单数量", context())
    assert first.success and second.success
    assert first.sql == second.sql
