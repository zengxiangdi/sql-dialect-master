"""Phase 1 contracts for rendering derived distinct count plans."""

import sqlglot
import pytest

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_pipeline.ir import DistinctCountPlan, build_ir
from backend.core.nl2sql_pipeline.renderer import render_sql
from backend.core.nl2sql_schema import SchemaContext


def render_plan(
    *,
    group_by=None,
    conditions=None,
    ordering=None,
    orderings=None,
    limit=None,
    plan=None,
    operation="SELECT",
    joins=None,
    aggregations=None,
    distinct=False,
):
    ir = build_ir(
        operation,
        "orders",
        ["*"],
        conditions or [],
        aggregations or [],
        group_by or [],
        ordering,
        limit,
        joins or [],
        distinct,
        "postgres",
        orderings=orderings,
        distinct_count_plan=plan,
    )
    return render_sql(ir)


PLAN = DistinctCountPlan(("tenant_id", "id"))


def test_plan_with_group_renders_exact_derived_sql():
    sql, explanation, confidence, _ = render_plan(
        plan=PLAN,
        group_by=["user_id"],
        conditions=["amount > 10"],
    )

    assert sql == (
        "-- Generated for POSTGRES\n"
        "SELECT user_id, COUNT(*) AS count\n"
        "FROM (\n"
        "    SELECT DISTINCT user_id, tenant_id, id\n"
        "    FROM orders\n"
        "    WHERE amount > 10 AND tenant_id IS NOT NULL AND id IS NOT NULL\n"
        ") AS _distinct_targets\n"
        "GROUP BY user_id"
    )
    assert explanation == "聚合: COUNT(*) AS count | 表: orders | 条件: 1个 | 分组: user_id"
    assert confidence > 0


def test_plan_without_group_renders_scalar_count():
    sql, _, _, _ = render_plan(plan=PLAN)

    assert sql == (
        "-- Generated for POSTGRES\n"
        "SELECT COUNT(*) AS count\n"
        "FROM (\n"
        "    SELECT DISTINCT tenant_id, id\n"
        "    FROM orders\n"
        "    WHERE tenant_id IS NOT NULL AND id IS NOT NULL\n"
        ") AS _distinct_targets"
    )


def test_plan_can_keep_null_identity_values_when_requested():
    sql, _, _, _ = render_plan(plan=DistinctCountPlan(("tenant_id", "id"), False))

    assert "WHERE" not in sql


def test_group_identity_overlap_is_projected_once():
    sql, _, _, _ = render_plan(plan=PLAN, group_by=["tenant_id"])

    assert "SELECT DISTINCT tenant_id, id" in sql
    assert "GROUP BY tenant_id" in sql


def test_ordering_is_rendered_on_outer_query_before_limit():
    sql, explanation, _, _ = render_plan(
        plan=PLAN,
        group_by=["user_id"],
        ordering=("user_id", "DESC"),
        limit=5,
    )

    assert sql.index("GROUP BY user_id") < sql.index("ORDER BY user_id DESC")
    assert sql.index("ORDER BY user_id DESC") < sql.index("LIMIT 5")
    assert "ORDER BY" not in sql.split("FROM (", 1)[1].split(") AS", 1)[0]
    assert "排序: user_id DESC" in explanation


def test_orderings_list_is_rendered_on_outer_query():
    sql, explanation, _, _ = render_plan(
        plan=PLAN,
        group_by=["user_id", "tenant_id"],
        orderings=[("user_id", "ASC"), ("tenant_id", "DESC")],
    )

    assert "ORDER BY user_id ASC, tenant_id DESC" in sql
    assert "排序: user_id ASC, tenant_id DESC" in explanation


@pytest.mark.parametrize("field", ["joins", "distinct", "aggregations"])
def test_plan_conflicting_query_features_fail_closed(field):
    kwargs = {field: [{"table": "users"}] if field == "joins" else True}
    if field == "aggregations":
        kwargs[field] = ["SUM(amount)"]
    sql, explanation, confidence, _ = render_plan(plan=PLAN, **kwargs)

    assert sql is None
    assert confidence == 0.0
    assert "Derived distinct count plan rejected" in explanation


def test_plan_non_select_fails_closed():
    sql, _, confidence, _ = render_plan(plan=PLAN, operation="UPDATE")

    assert sql is None
    assert confidence == 0.0


def test_plan_rejects_unsafe_identifiers_and_aggregate_alias_ordering():
    unsafe = render_plan(plan=DistinctCountPlan(("id; DROP TABLE users",)))
    alias = render_plan(plan=PLAN, group_by=["user_id"], ordering=("count", "DESC"))

    assert unsafe[0] is None and unsafe[2] == 0.0
    assert alias[0] is None and alias[2] == 0.0


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_derived_plan_is_parseable_in_all_dialects(dialect):
    ir = build_ir(
        "SELECT", "orders", ["*"], ["amount > 10"], [], ["user_id"],
        None, 5, [], False, dialect,
        orderings=[("user_id", "DESC")],
        distinct_count_plan=PLAN,
    )
    sql, _, _, _ = render_sql(ir)

    assert sql is not None
    assert sqlglot.parse_one(sql, read=dialect) is not None


def test_plan_none_preserves_legacy_renderer_path():
    legacy = build_ir(
        "SELECT", "orders", ["*"], [], ["COUNT(*) AS count"], ["user_id"],
        None, None, [], False, "postgres",
    )
    sql, _, _, _ = render_sql(legacy)

    assert sql == (
        "-- Generated for POSTGRES\n"
        "SELECT user_id, COUNT(*) AS count\n"
        "FROM orders\n"
        "GROUP BY user_id"
    )


def test_build_ir_old_positional_call_remains_compatible():
    ir = build_ir(
        "SELECT", "orders", ["*"], [], [], [], None, None, [], False, "postgres"
    )

    assert ir.distinct_count_plan is None
    assert ir.orderings is None


def test_composite_unique_count_is_not_enabled_by_phase_one():
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "orders", "columns": [
                {"name": "tenant_id"}, {"name": "id"}, {"name": "user_id"},
            ], "primary_key": ["tenant_id", "id"]},
        ],
        "relationships": [],
    })
    result = NL2SQLGenerator().generate(
        "count distinct orders per user", "postgres", schema=schema
    )

    assert result.success is False
    assert result.sql is None


def test_derived_plan_rendering_is_deterministic():
    first = render_plan(plan=PLAN, group_by=["user_id"], conditions=["amount > 10"])
    second = render_plan(plan=PLAN, group_by=["user_id"], conditions=["amount > 10"])

    assert first == second
