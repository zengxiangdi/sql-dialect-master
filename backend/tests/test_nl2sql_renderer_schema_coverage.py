"""Behavioral contracts for rendering query plans and validating schema references."""

from dataclasses import replace

import pytest
import sqlglot
from sqlglot import exp

from backend.core.nl2sql_components.evidence import (
    EVIDENCE_CONDITIONS_PRESENT,
    EVIDENCE_PARSE_FAIL,
    EVIDENCE_PARSE_OK,
)
from backend.core.nl2sql_pipeline.ir import (
    AggregateOrderingTerm,
    DistinctCountPlan,
    PathCondition,
    PathDistinctCountPlan,
    PathOrderingTerm,
    PathStep,
    QueryIR,
)
from backend.core.nl2sql_pipeline.renderer import render_sql
from backend.core.nl2sql_schema import (
    SchemaContext,
    SchemaValidationError,
    validate_schema_references,
)

PATH = PathDistinctCountPlan(
    subject_table="users",
    path_steps=(PathStep("users", "orders", (("id", "user_id"),)),),
    group_identity=("id",),
    target_identity=("id",),
)


def _select_ir() -> QueryIR:
    return QueryIR(
        operation="SELECT",
        table="users",
        columns=["*"],
        conditions=[],
        aggregations=[],
        group_by=[],
        ordering=None,
        limit=None,
        joins=[],
        distinct=False,
        dialect="postgres",
    )


@pytest.mark.parametrize(
    ("plan", "reason"),
    [
        (replace(PATH, path_steps=()), "one to three path steps are required"),
        (replace(PATH, subject_table="accounts"), "subject table is invalid"),
        (replace(PATH, group_identity=()), "group and target identities are required"),
        (replace(PATH, target_identity=("order id",)), "identity columns are invalid"),
        (
            replace(PATH, path_steps=(PathStep("accounts", "orders", (("id", "user_id"),)),)),
            "path step is invalid",
        ),
        (
            replace(PATH, path_steps=(PathStep("users", "users", (("id", "manager_id"),)),)),
            "path repeats a table",
        ),
    ],
)
def test_renderer_rejects_invalid_path_plan(plan: PathDistinctCountPlan, reason: str) -> None:
    ir = replace(_select_ir(), path_distinct_count_plan=plan)
    sql, explanation, confidence, evidence = render_sql(ir)

    assert sql is None
    assert explanation == f"Derived distinct count plan rejected: {reason}"
    assert confidence == 0
    assert evidence.items == []


@pytest.mark.parametrize(
    ("condition", "reason"),
    [
        (PathCondition("orders", "status", "=", "NULL"), "NULL path condition requires IS or IS NOT"),
        (PathCondition("orders", "status", "IS", "'paid'"), "IS path condition requires NULL"),
    ],
)
def test_zero_count_path_rejects_invalid_null_comparisons(condition: PathCondition, reason: str) -> None:
    plan = replace(PATH, include_zero=True, path_conditions=(condition,))
    sql, explanation, confidence, evidence = render_sql(replace(_select_ir(), path_distinct_count_plan=plan))

    assert sql is None
    assert explanation == f"Derived distinct count plan rejected: {reason}"
    assert confidence == 0
    assert evidence.items == []


def test_zero_count_path_rejects_group_ordering_outside_subject_identity() -> None:
    plan = replace(PATH, include_zero=True, path_orderings=(PathOrderingTerm("group", "status", "DESC"),))
    sql, explanation, confidence, evidence = render_sql(replace(_select_ir(), path_distinct_count_plan=plan))

    assert sql is None
    assert explanation == "Derived distinct count plan rejected: path ordering must use subject group identity"
    assert confidence == 0
    assert evidence.items == []


def test_renderer_omits_where_and_order_for_unfiltered_count_path() -> None:
    plan = replace(PATH, exclude_null_identity=False)
    sql, explanation, confidence, evidence = render_sql(replace(_select_ir(), path_distinct_count_plan=plan))

    assert sql == (
        "-- Generated for POSTGRES\n"
        "SELECT _group_0, COUNT(*) AS count\n"
        "FROM (\n"
        "    SELECT DISTINCT users.id AS _group_0, orders.id AS _target_0\n"
        "    FROM users\n"
        "    JOIN orders ON users.id = orders.user_id\n"
        ") AS _distinct_targets\n"
        "GROUP BY _group_0"
    )
    assert "条件:" not in explanation and "排序:" not in explanation
    assert confidence > 0
    assert EVIDENCE_PARSE_OK in {item.evidence_id for item in evidence.items}
    assert EVIDENCE_CONDITIONS_PRESENT not in {item.evidence_id for item in evidence.items}


def test_renderer_rejects_conflicting_derived_count_plans() -> None:
    ir = replace(_select_ir(), distinct_count_plan=DistinctCountPlan(("id",)), path_distinct_count_plan=PATH)
    sql, explanation, confidence, evidence = render_sql(ir)

    assert sql is None
    assert explanation == "Derived distinct count plan rejected: multiple derived count plans are unsupported"
    assert confidence == 0
    assert evidence.items == []


@pytest.mark.parametrize(
    ("table", "group_by", "reason"),
    [
        ("order items", [], "source table is invalid"),
        ("users", ["user status"], "group columns are invalid"),
    ],
)
def test_distinct_count_rejects_invalid_identifiers(table: str, group_by: list[str], reason: str) -> None:
    ir = replace(_select_ir(), table=table, group_by=group_by, distinct_count_plan=DistinctCountPlan(("id",)))
    sql, explanation, confidence, evidence = render_sql(ir)

    assert sql is None
    assert explanation == f"Derived distinct count plan rejected: {reason}"
    assert confidence == 0
    assert evidence.items == []


@pytest.mark.parametrize(
    ("plan", "path_plan"),
    [
        (DistinctCountPlan(("id",)), None),
        (None, PATH),
        (None, replace(PATH, include_zero=True)),
    ],
    ids=["distinct-count", "path-count", "zero-count-path"],
)
def test_renderer_discards_derived_sql_when_parser_rejects_predicate(
    plan: DistinctCountPlan | None,
    path_plan: PathDistinctCountPlan | None,
) -> None:
    ir = replace(_select_ir(), conditions=["status ="], distinct_count_plan=plan, path_distinct_count_plan=path_plan)
    sql, explanation, confidence, evidence = render_sql(ir)

    assert sql is None
    assert explanation.startswith("Generated SQL failed target-dialect validation:")
    assert confidence == 0
    assert evidence.items[-1].evidence_id == EVIDENCE_PARSE_FAIL
    assert evidence.items[-1].weight == -0.2


@pytest.mark.parametrize(
    ("terms", "group_by", "reason"),
    [
        ((AggregateOrderingTerm("count", None, "ASC"),), [], "aggregate ordering requires grouped query"),
        ((AggregateOrderingTerm("count", None, "SIDEWAYS"),), ["status"], "aggregate ordering term is invalid"),
        ((AggregateOrderingTerm("group", "id", "ASC"),), ["status"], "aggregate ordering column is invalid"),
        (
            (AggregateOrderingTerm("count", None, "ASC"), AggregateOrderingTerm("count", None, "DESC")),
            ["status"],
            "duplicate aggregate ordering",
        ),
    ],
)
def test_renderer_rejects_invalid_grouped_count_ordering(
    terms: tuple[AggregateOrderingTerm, ...],
    group_by: list[str],
    reason: str,
) -> None:
    ir = replace(
        _select_ir(),
        aggregations=["COUNT(DISTINCT id) AS count"],
        group_by=group_by,
        aggregate_orderings=terms,
    )
    sql, explanation, confidence, evidence = render_sql(ir)

    assert sql is None
    assert explanation == f"Derived distinct count plan rejected: {reason}"
    assert confidence == 0
    assert evidence.items == []


def test_renderer_rejects_ordinary_ordering_combined_with_aggregate_ordering() -> None:
    ir = replace(
        _select_ir(),
        aggregations=["COUNT(DISTINCT id) AS count"],
        group_by=["status"],
        ordering=("status", "ASC"),
        aggregate_orderings=(AggregateOrderingTerm("count", None, "ASC"),),
    )
    sql, explanation, confidence, evidence = render_sql(ir)

    assert sql is None
    assert explanation == "Derived distinct count plan rejected: generic and aggregate orderings cannot be combined"
    assert confidence == 0
    assert evidence.items == []


def test_renderer_uses_positional_marker_for_generated_duckdb_delete() -> None:
    ir = replace(_select_ir(), operation="DELETE", dialect="duckdb")
    sql, explanation, confidence, evidence = render_sql(ir)

    assert sql == "-- Generated for DUCKDB\nDELETE FROM users\nWHERE id = ?"
    assert explanation == "删除: users"
    assert confidence > 0
    assert evidence.items[-1].evidence_id == EVIDENCE_PARSE_OK


USERS = {"name": "users", "columns": [{"name": "id"}, {"name": "status"}]}


@pytest.mark.parametrize(
    "mapping",
    [
        {"tables": "users"},
        {"tables": ["users"]},
        {"tables": [{"name": 42}]},
        {"tables": [{"name": "user data"}]},
        {"tables": [{"name": "users", "columns": "id"}]},
        {"tables": [{"name": "users", "columns": ["id"]}]},
        {"tables": [{"name": "users", "columns": [{"name": "user id"}]}]},
        {"tables": [USERS, {"name": "USERS"}]},
        {"tables": [{**USERS, "primary_key": ["id", "ID"]}]},
        {
            "tables": [USERS],
            "relationships": [
                {"from_table": "users", "to_table": "missing", "from_column": "id", "to_column": "id"},
            ],
        },
    ],
    ids=[
        "non-list-tables",
        "non-mapping-table",
        "non-string-identifier",
        "invalid-table-identifier",
        "non-list-columns",
        "non-mapping-column",
        "invalid-column-identifier",
        "duplicate-table",
        "duplicate-primary-key",
        "unknown-relationship-target",
    ],
)
def test_malformed_schema_is_rejected_by_reference_validation(mapping: dict[str, object]) -> None:
    statement = sqlglot.parse_one("SELECT users.id FROM users", into=exp.Select)
    context = SchemaContext.from_mapping(mapping)

    assert not context.is_valid
    with pytest.raises(SchemaValidationError, match="^invalid schema$"):
        validate_schema_references(statement, context)


def test_composite_relationship_requires_column_pairs_in_both_directions() -> None:
    context = SchemaContext.from_mapping({
        "tables": [
            {"name": "orders", "columns": [{"name": "tenant_id"}, {"name": "user_id"}]},
            {"name": "users", "columns": [{"name": "tenant_id"}, {"name": "id"}], "primary_key": ["tenant_id", "id"]},
        ],
        "relationships": [
            {
                "from_table": "orders",
                "to_table": "users",
                "columns": [
                    {"from_column": "tenant_id", "to_column": "tenant_id"},
                    {"from_column": "user_id", "to_column": "id"},
                ],
            },
        ],
    })

    assert context.is_valid
    forward, = context.relationship_candidates("orders", "users")
    reverse, = context.relationship_candidates("users", "orders")
    assert forward.column_pairs == (("tenant_id", "tenant_id"), ("user_id", "id"))
    assert reverse.column_pairs == (("tenant_id", "tenant_id"), ("id", "user_id"))
    with pytest.raises(SchemaValidationError, match="no single from_column"):
        _ = forward.from_column
    with pytest.raises(SchemaValidationError, match="no single to_column"):
        _ = reverse.to_column


def test_schema_reference_validation_rejects_unknown_source_alias() -> None:
    statement = sqlglot.parse_one("SELECT account.id FROM users", into=exp.Select)

    with pytest.raises(SchemaValidationError, match="^unknown SQL table alias$"):
        validate_schema_references(statement, {"tables": [USERS]})
