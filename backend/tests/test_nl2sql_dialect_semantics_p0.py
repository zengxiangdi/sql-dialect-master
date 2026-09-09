import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator


@pytest.fixture()
def generator():
    return NL2SQLGenerator()


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("postgres", "CURRENT_DATE - INTERVAL '7 days'"),
        ("mysql", "DATE_SUB(CURRENT_DATE, 7)"),
        ("oracle", "TRUNC(SYSDATE) - 7"),
        ("tsql", "DATEADD(DAY, -7, CAST(GETDATE() AS DATE))"),
        ("duckdb", "CURRENT_DATE - INTERVAL '7 days'"),
    ],
)
def test_recent_days_date_semantics(generator, dialect, expected):
    result = generator.generate("查询最近7天的订单", dialect=dialect, table_hint="orders")
    assert result.success, result.explanation
    assert expected in result.sql

    sql_without_comments = "\n".join(
        line for line in result.sql.splitlines() if not line.strip().startswith("--")
    )
    sqlglot.parse_one(sql_without_comments, read=dialect)


def test_date_add_and_current_timestamp_are_dialect_specific(generator):
    source = "SELECT DATE_ADD(CURRENT_DATE, 7), ADD_MONTHS(CURRENT_DATE, 1), CURRENT_TIMESTAMP FROM orders"
    expected = {
        "mysql": ("DATE_ADD", "ADD_MONTHS", "CURRENT_TIMESTAMP"),
        "postgres": ("CURRENT_DATE + INTERVAL '7 days'", "CURRENT_DATE + INTERVAL '1 month'", "CURRENT_TIMESTAMP"),
        "oracle": ("TRUNC(SYSDATE) + 7", "ADD_MONTHS(TRUNC(SYSDATE), 1)", "SYSTIMESTAMP"),
        "tsql": ("DATEADD(DAY, 7, CAST(GETDATE() AS DATE))", "DATEADD(MONTH, 1, CAST(GETDATE() AS DATE))", "SYSDATETIME()"),
        "duckdb": ("CURRENT_DATE + INTERVAL '7 days'", "CURRENT_DATE + INTERVAL '1 month'", "CURRENT_TIMESTAMP"),
    }
    for dialect, fragments in expected.items():
        adjusted = generator._apply_dialect_adjustments(source, dialect)
        for fragment in fragments:
            assert fragment in adjusted


def test_oracle_adjustment_does_not_delete_parentheses_or_touch_literals(generator):
    sql = """SELECT COALESCE(amount, 0), 'CURRENT_DATE DATE_SUB(x, 1)'
FROM orders
WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)"""

    adjusted = generator._apply_dialect_adjustments(sql, "oracle")

    assert "COALESCE(amount, 0)" in adjusted
    assert "'CURRENT_DATE DATE_SUB(x, 1)'" in adjusted
    assert "TRUNC(SYSDATE) - 7" in adjusted
    assert adjusted.count("(") == adjusted.count(")")


def test_tsql_adjustment_preserves_nested_expression_parentheses(generator):
    sql = "SELECT COALESCE(amount, 0) FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)"
    adjusted = generator._apply_dialect_adjustments(sql, "tsql")

    assert "COALESCE(amount, 0)" in adjusted
    assert "DATEADD(DAY, -7, CAST(GETDATE() AS DATE))" in adjusted
    assert adjusted.count("(") == adjusted.count(")")


def test_postgres_interval_rewrite_uses_actual_number(generator):
    sql = "SELECT * FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)"
    adjusted = generator._apply_dialect_adjustments(sql, "postgres")

    assert "CURRENT_DATE - INTERVAL '7 days'" in adjusted
    assert "\\1 days" not in adjusted


def test_null_predicates_are_explicit(generator):
    for text, predicate in [
        ("查询年龄为空的用户", "age IS NULL"),
        ("查询年龄不为空的用户", "age IS NOT NULL"),
    ]:
        result = generator.generate(text, dialect="postgres", table_hint="users")
        assert result.success
        assert predicate in result.sql


def test_top_n_uses_dialect_specific_syntax(generator):
    expectations = {
        "postgres": "LIMIT 5",
        "mysql": "LIMIT 5",
        "duckdb": "LIMIT 5",
        "oracle": "FETCH FIRST 5 ROWS ONLY",
        "tsql": "TOP 5",
    }
    for dialect, expected in expectations.items():
        result = generator.generate(
            "前5名用户",
            dialect=dialect,
            table_hint="users",
            column_hints=["id"],
        )
        assert result.success
        assert expected in result.sql


def test_aggregation_with_group_by_is_structurally_valid(generator):
    result = generator.generate(
        "统计每个部门的员工数量",
        dialect="postgres",
        table_hint="employees",
        column_hints=["department", "id"],
    )
    assert result.success
    sql = "\n".join(line for line in result.sql.splitlines() if not line.startswith("--"))
    tree = sqlglot.parse_one(sql, read="postgres")
    assert tree.args.get("group") is not None
    assert "COUNT" in sql.upper()


def test_dml_generation_has_explicit_predicates(generator):
    update = generator.generate(
        "更新用户年龄大于30",
        dialect="postgres",
        table_hint="users",
        column_hints=["age"],
    )
    delete = generator.generate(
        "删除用户年龄大于30",
        dialect="postgres",
        table_hint="users",
        column_hints=["age"],
    )
    assert update.success and "UPDATE users" in update.sql and "WHERE" in update.sql
    assert delete.success and "DELETE FROM users" in delete.sql and "WHERE" in delete.sql
