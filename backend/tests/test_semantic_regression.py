"""Semantic regression tests for NL2SQL and cross-dialect transpilation."""

import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.transpiler import SQLTranspiler
from backend.core.type_mapping import TypeMapper


nl2sql = NL2SQLGenerator()
transpiler = SQLTranspiler()
type_mapper = TypeMapper()


def parse_sql(sql: str, dialect: str) -> exp.Expression:
    """Parse generated SQL with its target dialect and fail with useful context."""
    return sqlglot.parse_one(sql, read=dialect)


def table_names(tree: exp.Expression) -> set[str]:
    return {table.name.lower() for table in tree.find_all(exp.Table)}


def column_names(tree: exp.Expression) -> list[str]:
    return [column.name.lower() for column in tree.find_all(exp.Column)]


def test_nl2sql_group_count_preserves_table_group_and_aggregation():
    result = nl2sql.generate("count orders by status", "mysql")

    assert result.success
    tree = parse_sql(result.sql, "mysql")

    assert table_names(tree) == {"orders"}
    assert "status" in column_names(tree)
    assert tree.find(exp.Group) is not None
    count = tree.find(exp.Count)
    assert count is not None
    assert count.this is not None


def test_nl2sql_condition_preserves_predicate_semantics():
    result = nl2sql.generate("find products with price greater than 100", "postgres")

    assert result.success
    tree = parse_sql(result.sql, "postgres")
    where = tree.find(exp.Where)

    assert table_names(tree) == {"products"}
    assert where is not None
    predicate_sql = where.this.sql(dialect="postgres").upper()
    assert "PRICE" in predicate_sql
    assert ">" in predicate_sql
    assert "100" in predicate_sql


def test_nl2sql_composed_condition_preserves_order_and_limit():
    result = nl2sql.generate(
        "find products with price greater than 100 order by price desc limit 10",
        "postgres",
    )

    assert result.success
    tree = parse_sql(result.sql, "postgres")

    assert table_names(tree) == {"products"}
    where = tree.find(exp.Where)
    assert where is not None
    predicate_sql = where.this.sql(dialect="postgres").upper()
    assert "PRICE" in predicate_sql
    assert ">" in predicate_sql
    assert "100" in predicate_sql

    order = tree.find(exp.Order)
    assert order is not None
    assert "PRICE" in order.sql(dialect="postgres").upper()
    assert "DESC" in order.sql(dialect="postgres").upper()

    limit = tree.find(exp.Limit)
    assert limit is not None
    assert limit.expression is not None
    assert limit.expression.sql(dialect="postgres") == "10"


def test_nl2sql_composed_aggregate_preserves_group_and_order():
    result = nl2sql.generate(
        "calculate average price for products grouped by category order by average price desc",
        "postgres",
    )

    assert result.success
    tree = parse_sql(result.sql, "postgres")

    assert table_names(tree) == {"products"}
    assert tree.find(exp.Avg) is not None
    group = tree.find(exp.Group)
    assert group is not None
    assert "category" in group.sql(dialect="postgres").lower()
    order = tree.find(exp.Order)
    assert order is not None
    assert "DESC" in order.sql(dialect="postgres").upper()


def test_nl2sql_top_n_preserves_order_and_limit():
    result = nl2sql.generate("select top 10 customers", "mysql")

    assert result.success
    tree = parse_sql(result.sql, "mysql")
    order = tree.find(exp.Order)
    limit = tree.find(exp.Limit)

    assert table_names(tree) == {"customers"}
    assert order is not None
    assert limit is not None
    assert limit.expression is not None
    assert limit.expression.sql(dialect="mysql") == "10"


def test_mysql_to_postgres_preserves_selected_columns_filter_and_order():
    source_sql = "SELECT id, name FROM users WHERE status = 1 ORDER BY created_at DESC LIMIT 10"
    result = transpiler.transpile(source_sql, "mysql", "postgres")

    assert result.success
    source = parse_sql(source_sql, "mysql")
    target = parse_sql(result.target_sql, "postgres")

    assert table_names(source) == table_names(target) == {"users"}
    assert column_names(target)[:2] == ["id", "name"]

    source_where = source.find(exp.Where)
    target_where = target.find(exp.Where)
    assert source_where is not None and target_where is not None
    assert source_where.this.sql(dialect="postgres") == target_where.this.sql(dialect="postgres")

    assert target.find(exp.Order) is not None
    assert target.find(exp.Limit) is not None


def test_tsql_to_hive_preserves_top_n_semantics():
    source_sql = "SELECT TOP 10 id, name FROM users ORDER BY created_at DESC"
    result = transpiler.transpile(source_sql, "tsql", "hive")

    assert result.success
    target = parse_sql(result.target_sql, "hive")

    assert table_names(target) == {"users"}
    assert target.find(exp.Order) is not None
    limit = target.find(exp.Limit)
    assert limit is not None
    assert limit.expression.sql(dialect="hive") == "10"
    assert "TOP" not in result.target_sql.upper()


def test_hive_to_oracle_preserves_window_partition_and_order():
    source_sql = (
        "SELECT user_id, amount, "
        "ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) AS rn "
        "FROM orders"
    )
    result = transpiler.transpile(source_sql, "hive", "oracle")

    assert result.success
    source = parse_sql(source_sql, "hive")
    target = parse_sql(result.target_sql, "oracle")

    assert table_names(source) == table_names(target) == {"orders"}
    source_window = source.find(exp.Window)
    target_window = target.find(exp.Window)
    assert source_window is not None and target_window is not None
    assert source_window.sql(dialect="oracle") == target_window.sql(dialect="oracle")


def test_type_mapper_unknown_dialect_is_not_reported_as_success():
    result = type_mapper.map_type("VARCHAR", "mysql", "made_up_db")

    assert result["success"] is False
    assert result["target_type"] is None
    assert "made_up_db" in result["error"]
