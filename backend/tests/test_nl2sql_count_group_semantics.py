import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator


def test_count_by_group_honors_column_hint_and_requested_count_order() -> None:
    generator = NL2SQLGenerator()

    result = generator.generate(
        "统计每个部门的员工数量并按数量排序",
        dialect="postgres",
        table_hint="employees",
        column_hints=["department", "id"],
    )

    assert result.success, result.explanation
    sql = "\n".join(
        line for line in result.sql.splitlines() if not line.strip().startswith("--")
    )
    tree = sqlglot.parse_one(sql, read="postgres")

    assert "SELECT department, COUNT(*) AS count" in sql
    assert tree.args["group"].expressions[0].sql() == "department"
    order = tree.find(exp.Order)
    assert order is not None
    assert order.expressions[0].this.sql() == "count"
    assert order.expressions[0].args.get("desc") is True


def test_count_by_group_without_order_language_keeps_existing_shape() -> None:
    generator = NL2SQLGenerator()

    result = generator.generate(
        "统计每个部门的员工数量",
        dialect="postgres",
        table_hint="employees",
        column_hints=["department", "id"],
    )

    assert result.success, result.explanation
    sql = "\n".join(
        line for line in result.sql.splitlines() if not line.strip().startswith("--")
    )
    tree = sqlglot.parse_one(sql, read="postgres")

    assert "SELECT department, COUNT(*) AS count" in sql
    assert tree.find(exp.Order) is None
