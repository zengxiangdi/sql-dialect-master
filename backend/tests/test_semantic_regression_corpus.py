from dataclasses import dataclass

import pytest
import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator


@dataclass(frozen=True)
class NL2SQLCase:
    name: str
    text: str
    dialect: str
    table: str
    columns: tuple[str, ...] = ()
    must_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    require_where: bool = False
    require_group: bool = False
    require_order: bool = False
    require_limit: bool = False
    require_boolean_and_or: bool = False
    operation: str = "SELECT"


CASES = (
    NL2SQLCase(
        "recent-days-postgres",
        "查询最近7天的订单",
        "postgres",
        "orders",
        must_contain=("CURRENT_DATE - INTERVAL '7 days'",),
        require_where=True,
    ),
    NL2SQLCase(
        "recent-days-mysql",
        "查询最近7天的订单",
        "mysql",
        "orders",
        must_contain=("DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)",),
        require_where=True,
    ),
    NL2SQLCase(
        "recent-days-oracle",
        "查询最近7天的订单",
        "oracle",
        "orders",
        must_contain=("TRUNC(SYSDATE) - 7",),
        require_where=True,
    ),
    NL2SQLCase(
        "recent-days-tsql",
        "查询最近7天的订单",
        "tsql",
        "orders",
        must_contain=("DATEADD(DAY, -7, CAST(GETDATE() AS DATE))",),
        require_where=True,
    ),
    NL2SQLCase(
        "recent-days-duckdb",
        "查询最近7天的订单",
        "duckdb",
        "orders",
        must_contain=("CURRENT_DATE - INTERVAL '7 days'",),
        require_where=True,
    ),
    NL2SQLCase(
        "null-is-null",
        "查询年龄为空的用户",
        "postgres",
        "users",
        columns=("age",),
        must_contain=("age IS NULL",),
        require_where=True,
    ),
    NL2SQLCase(
        "null-is-not-null",
        "查询年龄不为空的用户",
        "postgres",
        "users",
        columns=("age",),
        must_contain=("age IS NOT NULL",),
        must_not_contain=("age IS NULL",),
        require_where=True,
    ),
    NL2SQLCase(
        "top-n-postgres",
        "前5名用户",
        "postgres",
        "users",
        columns=("id",),
        must_contain=("ORDER BY", "DESC", "LIMIT 5"),
        require_order=True,
        require_limit=True,
    ),
    NL2SQLCase(
        "top-n-oracle",
        "前5名用户",
        "oracle",
        "users",
        columns=("id",),
        must_contain=("ORDER BY", "DESC", "FETCH FIRST 5 ROWS ONLY"),
        require_order=True,
        require_limit=True,
    ),
    NL2SQLCase(
        "top-n-tsql",
        "前5名用户",
        "tsql",
        "users",
        columns=("id",),
        must_contain=("SELECT TOP 5", "ORDER BY", "DESC"),
        require_order=True,
        require_limit=True,
    ),
    NL2SQLCase(
        "bottom-n-postgres",
        "最低5名用户",
        "postgres",
        "users",
        columns=("id",),
        must_contain=("ORDER BY", "ASC", "LIMIT 5"),
        require_order=True,
        require_limit=True,
    ),
    NL2SQLCase(
        "aggregate-group-order",
        "统计每个部门的员工数量并按数量排序",
        "postgres",
        "employees",
        columns=("department", "id"),
        must_contain=("COUNT", "GROUP BY", "ORDER BY"),
        require_group=True,
        require_order=True,
    ),
    NL2SQLCase(
        "boolean-and-or",
        "查询年龄大于18且评分大于80或浏览量大于1000的用户",
        "postgres",
        "users",
        columns=("age", "score", "views"),
        must_contain=("AND", "OR"),
        require_where=True,
        require_boolean_and_or=True,
    ),
    NL2SQLCase(
        "update-explicit-predicate",
        "更新用户年龄大于30",
        "postgres",
        "users",
        columns=("age",),
        must_contain=("UPDATE users", "WHERE", "age > 30"),
        require_where=True,
        operation="UPDATE",
    ),
    NL2SQLCase(
        "delete-explicit-predicate",
        "删除用户年龄大于30",
        "postgres",
        "users",
        columns=("age",),
        must_contain=("DELETE FROM users", "WHERE", "age > 30"),
        require_where=True,
        operation="DELETE",
    ),
)


@pytest.fixture()
def generator() -> NL2SQLGenerator:
    return NL2SQLGenerator()


def _sql_without_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


def _contains_limit(tree: exp.Expression) -> bool:
    return tree.find(exp.Limit) is not None or tree.find(exp.Fetch) is not None


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_nl2sql_corpus_cases_are_semantically_parseable(generator: NL2SQLGenerator, case: NL2SQLCase) -> None:
    result = generator.generate(
        case.text,
        dialect=case.dialect,
        table_hint=case.table,
        column_hints=list(case.columns) or None,
    )

    assert result.success, result.explanation
    sql = _sql_without_comments(result.sql)
    tree = sqlglot.parse_one(sql, read=case.dialect)

    operation = tree.find(exp.Update) or tree.find(exp.Delete)
    if case.operation == "SELECT":
        assert isinstance(tree, (exp.Select, exp.Union, exp.With)) or operation is None
    else:
        assert operation is not None

    for fragment in case.must_contain:
        assert fragment in sql
    for fragment in case.must_not_contain:
        assert fragment not in sql

    if case.require_where:
        assert tree.find(exp.Where) is not None
    if case.require_group:
        assert tree.args.get("group") is not None
    if case.require_order:
        assert tree.find(exp.Order) is not None
    if case.require_limit:
        assert _contains_limit(tree)
    if case.require_boolean_and_or:
        where = tree.find(exp.Where)
        assert where is not None
        assert where.this.find(exp.And) is not None
        assert where.this.find(exp.Or) is not None


def test_corpus_contracts_are_unique() -> None:
    names = [case.name for case in CASES]
    assert len(names) == len(set(names))


def test_corpus_keeps_dialect_coverage_balanced() -> None:
    dialects = {case.dialect for case in CASES}
    assert {"postgres", "mysql", "oracle", "tsql", "duckdb"}.issubset(dialects)
