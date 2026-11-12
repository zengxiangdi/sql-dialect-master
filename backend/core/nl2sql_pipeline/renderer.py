#!/usr/bin/env python3
"""P8 NL2SQL pipeline: SQL renderer (extracted from nl2sql_legacy).

``render_sql`` is the renamed, pure-function form of the legacy
``_build_sql_enhanced`` method.  Its body is behavior-identical to the
legacy version; it now operates on a ``QueryIR`` instead of flat
positional args and returns the same 4-tuple
``(sql, explanation, confidence, evidence)``.
"""
import re
from typing import Dict, List, Optional, Tuple, Union

from ..nl2sql_components.evidence import (
    EVIDENCE_AGGREGATION_PRESENT,
    EVIDENCE_COLUMNS_EXPLICIT,
    EVIDENCE_CONDITIONS_PRESENT,
    EVIDENCE_GROUP_BY,
    EVIDENCE_JOIN_KNOWN,
    EVIDENCE_LIMIT,
    EVIDENCE_PARSE_FAIL,
    EVIDENCE_PARSE_OK,
    EVIDENCE_TABLE_KNOWN,
    EvidenceItem,
    GenerationEvidence,
)
from .dialect import apply_dialect_adjustments
from .ir import (
    AggregateOrderingTerm,
    DistinctCountPlan,
    PathCondition,
    PathDistinctCountPlan,
    PathOrderingTerm,
    QueryIR,
)
from .validation import validate_sql


# ── Pure helper functions (moved verbatim from nl2sql_legacy) ───────────────

def join_sql_kind(join: Dict) -> str:
    """Return the SQL JOIN keyword for a physical join record.

    A structured ``join_spec`` from the relations module wins; an
    unqualified join or a missing spec falls back to INNER.  Physical
    join kinds never include EXISTS/NOT EXISTS — those are relational.
    """
    spec = join.get("join_spec")
    if spec is not None:
        kind = spec.kind
        return "INNER" if kind == "JOIN" else kind
    join_type = join.get("type", "JOIN")
    if join_type in ("EXISTS", "NOT EXISTS"):
        return "INNER"
    return "INNER" if join_type in ("JOIN", "INNER") else join_type


def add_limit(sql: str, limit: int, dialect: str) -> str:
    """Add LIMIT clause with dialect-specific syntax."""
    if dialect == "oracle":
        return f"{sql}\nFETCH FIRST {limit} ROWS ONLY"
    if dialect == "tsql":
        return sql.replace("SELECT", f"SELECT TOP {limit}", 1)
    return f"{sql}\nLIMIT {limit}"


def parameter_placeholder(index: int, dialect: str) -> str:
    """Return a DB-API/native bind marker for ``dialect``.

    NL2SQL has no values to bind, so DML output is a parameterized template.
    A single ``?`` marker is not executable by several supported drivers
    (notably PostgreSQL, Oracle and T-SQL); use each target's conventional
    marker while keeping numbering stable across one statement.
    """
    dialect = (dialect or "").lower()
    if dialect in {"postgres", "redshift"}:
        return f"${index}"
    if dialect == "oracle":
        return f":{index}"
    if dialect == "tsql":
        return f"@p{index}"
    if dialect == "mysql":
        return "%s"
    # Hive/Spark/Trino/DuckDB/Snowflake and ClickHouse clients commonly accept
    # positional question-mark binds or adapt them at their DB-API boundary.
    return "?"


_SAFE_IDENTIFIER = re.compile(
    r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*"
)
_DERIVED_COUNT_ALIAS = "_distinct_targets"
_PATH_LITERAL = re.compile(
    r"(?:NULL|-?(?:\d+(?:\.\d*)?|\.\d+)|'(?:''|[^'])*')",
    re.IGNORECASE,
)


def _safe_identifier(value: str) -> bool:
    return isinstance(value, str) and _SAFE_IDENTIFIER.fullmatch(value) is not None


def _render_plan_failure(reason: str) -> Tuple[None, str, float, GenerationEvidence]:
    return None, f"Derived distinct count plan rejected: {reason}", 0.0, GenerationEvidence()


def _render_aggregate_orderings(
    terms: tuple[AggregateOrderingTerm, ...], group_by: list[str], count_expression: str,
) -> tuple[str, str | None]:
    if not terms or not group_by or len(terms) > 5:
        return "", "aggregate ordering requires grouped query" if terms else None
    keys = {c.casefold(): c for c in group_by}; seen = set(); rendered=[]; groups=set()
    for term in terms:
        if not isinstance(term, AggregateOrderingTerm) or term.direction not in {"ASC", "DESC"}:
            return "", "aggregate ordering term is invalid"
        if term.kind == "count" and term.column is None:
            key=("count",""); expression=count_expression
        elif term.kind == "group" and _safe_identifier(term.column or "") and (term.column or "").casefold() in keys:
            key=("group",(term.column or "").casefold()); groups.add(key[1]); expression=keys[key[1]]
        else:
            return "", "aggregate ordering column is invalid"
        if key in seen: return "", "duplicate aggregate ordering"
        seen.add(key); rendered.append(f"{expression} {term.direction}")
    for col in group_by:
        if col.casefold() not in groups: rendered.append(f"{col} ASC")
    return ", ".join(rendered), None


def _render_distinct_count_plan(
    ir: QueryIR,
) -> Tuple[Optional[str], str, float, GenerationEvidence]:
    """Render a validated composite-identity count through a derived table."""
    plan: DistinctCountPlan = ir.distinct_count_plan  # type: ignore[assignment]
    if ir.operation != "SELECT":
        return _render_plan_failure("only SELECT operations are supported")
    if ir.joins:
        return _render_plan_failure("joins are unsupported")
    if ir.distinct:
        return _render_plan_failure("DISTINCT projection is unsupported")
    if ir.aggregations:
        return _render_plan_failure("aggregations are unsupported")
    if not plan.identity_columns or any(
        not _safe_identifier(column) for column in plan.identity_columns
    ):
        return _render_plan_failure("identity columns are invalid")
    if not _safe_identifier(ir.table):
        return _render_plan_failure("source table is invalid")
    if any(not _safe_identifier(column) for column in ir.group_by):
        return _render_plan_failure("group columns are invalid")

    projection: list[str] = []
    seen: set[str] = set()
    for column in [*ir.group_by, *plan.identity_columns]:
        key = column.casefold()
        if key not in seen:
            seen.add(key)
            projection.append(column)
    if not projection:
        return _render_plan_failure("derived projection is empty")

    conditions = ir.conditions
    inner_conditions = (
        [condition for condition in conditions if condition.strip()]
        if isinstance(conditions, list)
        else ([conditions] if conditions.strip() else [])
    )
    if plan.exclude_null_identity:
        inner_conditions.extend(
            f"{column} IS NOT NULL" for column in plan.identity_columns
        )
    inner_sql = (
        f"SELECT DISTINCT {', '.join(projection)}\nFROM {ir.table}"
    )
    if inner_conditions:
        inner_sql += "\nWHERE " + " AND ".join(inner_conditions)
    indented_inner = "\n".join(
        f"    {line}" for line in inner_sql.splitlines()
    )

    select_clause = (
        ", ".join([*ir.group_by, "COUNT(*) AS count"])
        if ir.group_by
        else "COUNT(*) AS count"
    )
    sql = (
        f"SELECT {select_clause}\n"
        f"FROM (\n{indented_inner}\n) AS {_DERIVED_COUNT_ALIAS}"
    )
    explanation_parts = ["聚合: COUNT(*) AS count", f"表: {ir.table}"]
    evidence = ir.evidence
    evidence.items.append(EvidenceItem("base", "Base confidence for generated SQL", 0.5))
    evidence.items.append(EvidenceItem(
        EVIDENCE_AGGREGATION_PRESENT,
        "Derived distinct entity count",
        0.15,
        detail=", ".join(plan.identity_columns),
    ))
    if ir.table != "table_name":
        evidence.items.append(EvidenceItem(
            EVIDENCE_TABLE_KNOWN,
            f"Table resolved to known name: {ir.table}",
            0.2,
            detail=ir.table,
        ))
    if inner_conditions and isinstance(conditions, (list, str)) and conditions:
        explanation_parts.append(
            f"条件: {len(conditions) if isinstance(conditions, list) else 1}个"
        )
        evidence.items.append(EvidenceItem(
            EVIDENCE_CONDITIONS_PRESENT,
            "Explicit predicates in derived count input",
            0.1,
        ))
    if ir.group_by:
        explanation_parts.append(f"分组: {', '.join(ir.group_by)}")
        evidence.items.append(EvidenceItem(
            EVIDENCE_GROUP_BY,
            f"GROUP BY clause: {', '.join(ir.group_by)}",
            0.1,
        ))

    if ir.aggregate_orderings is not None and (ir.ordering or ir.orderings):
        return _render_plan_failure("generic and aggregate orderings cannot be combined")
    ordering_sql = ""
    if ir.aggregate_orderings:
        ordering_sql, ordering_error = _render_aggregate_orderings(
            ir.aggregate_orderings, ir.group_by, "COUNT(*)"
        )
        if ordering_error is not None:
            return _render_plan_failure(ordering_error)
        explanation_parts.append(f"排序: {ordering_sql}")
    else:
        active_orderings = ir.orderings or ([ir.ordering] if ir.ordering else [])
    if ir.aggregate_orderings is None and active_orderings:
        group_keys = {column.casefold() for column in ir.group_by}
        for column, direction in active_orderings:
            if (
                not _safe_identifier(column)
                or direction not in {"ASC", "DESC"}
                or column.casefold() == "count"
                or column.casefold() not in group_keys
            ):
                return _render_plan_failure(
                    "derived count ordering must use a grouped schema column"
                )
        ordering_sql = ", ".join(
            f"{column} {direction}" for column, direction in active_orderings
        )
        explanation_parts.append(f"排序: {ordering_sql}")
    if ir.group_by:
        sql += f"\nGROUP BY {', '.join(ir.group_by)}"
    if ordering_sql:
        sql += f"\nORDER BY {ordering_sql}"
    if ir.limit is not None:
        sql = add_limit(sql, ir.limit, ir.dialect)
        explanation_parts.append(f"限制: {ir.limit}条")
        evidence.items.append(EvidenceItem(
            EVIDENCE_LIMIT,
            f"Explicit limit: {ir.limit}",
            0.1,
            detail=str(ir.limit),
        ))

    sql = f"-- Generated for {ir.dialect.upper()}\n{sql}"
    sql = apply_dialect_adjustments(sql, ir.dialect)
    parse_adjustment = validate_sql(sql, ir.dialect)
    if parse_adjustment > 0:
        evidence.items.append(EvidenceItem(
            EVIDENCE_PARSE_OK,
            "Target dialect parser accepted the generated SQL",
            parse_adjustment,
        ))
    elif parse_adjustment < 0:
        evidence.items.append(EvidenceItem(
            EVIDENCE_PARSE_FAIL,
            "Target dialect parser rejected the generated SQL",
            parse_adjustment,
        ))
        return None, (
            "Generated SQL failed target-dialect validation: "
            + " | ".join(explanation_parts)
        ), 0.0, evidence
    return sql, " | ".join(explanation_parts), evidence.score, evidence


def _qualify_subject_condition(condition: str, subject_table: str) -> str:
    """Qualify simple whose predicates against the outer subject table."""
    pattern = re.compile(
        r"(?<![\w$.])([A-Za-z_][A-Za-z0-9_$]*)(?=\s*(?:=|!=|<>|>=|<=|>|<))"
    )
    return pattern.sub(lambda match: f"{subject_table}.{match.group(1)}", condition)


def _render_path_conditions(
    plan: PathDistinctCountPlan,
    path_tables: set[str],
) -> tuple[list[str], str | None]:
    """Validate and render intermediate/target-owned path predicates."""
    if not isinstance(plan.path_conditions, tuple):
        return [], "path condition collection is invalid"
    rendered: list[str] = []
    allowed_operators = {"=", "!=", ">", ">=", "<", "<=", "IS", "IS NOT"}
    for condition in plan.path_conditions:
        if (
            not isinstance(condition, PathCondition)
            or not _safe_identifier(condition.table)
            or condition.table.casefold() not in path_tables
            or not _safe_identifier(condition.column)
            or condition.operator not in allowed_operators
            or not isinstance(condition.literal, str)
            or _PATH_LITERAL.fullmatch(condition.literal) is None
        ):
            return [], "path condition is invalid"
        if condition.literal.upper() == "NULL":
            if condition.operator not in {"IS", "IS NOT"}:
                return [], "NULL path condition requires IS or IS NOT"
        elif condition.operator in {"IS", "IS NOT"}:
            return [], "IS path condition requires NULL"
        rendered.append(
            f"{condition.table}.{condition.column} "
            f"{condition.operator} {condition.literal}"
        )
    return rendered, None


def _render_path_orderings(
    plan: PathDistinctCountPlan,
    group_aliases: list[str],
    *,
    include_zero: bool,
) -> tuple[str, str | None]:
    """Validate and render typed path aggregate/group orderings."""
    if not isinstance(plan.path_orderings, tuple):
        return "", "path ordering collection is invalid"
    if len(plan.path_orderings) > 5:
        return "", "invalid or excessive path ordering"
    if not plan.path_orderings:
        return "", None
    alias_by_column = {
        column.casefold(): alias
        for column, alias in zip(plan.group_identity, group_aliases)
    }
    seen: set[tuple[str, str]] = set()
    rendered: list[str] = []
    ordered_groups: set[str] = set()
    for term in plan.path_orderings:
        if not isinstance(term, PathOrderingTerm) or term.direction not in {"ASC", "DESC"}:
            return "", "path ordering term is invalid"
        if term.kind == "count":
            if term.column is not None:
                return "", "count ordering cannot name a column"
            key = ("count", "")
            expression = "COALESCE(c.count, 0)" if include_zero else "COUNT(*)"
        elif term.kind == "group":
            if not _safe_identifier(term.column or ""):
                return "", "path group ordering column is invalid"
            key = ("group", (term.column or "").casefold())
            alias = alias_by_column.get(key[1])
            if alias is None:
                return "", "path ordering must use subject group identity"
            ordered_groups.add(key[1])
            expression = f"b.{alias}" if include_zero else alias
        else:
            return "", "path ordering kind is invalid"
        if key in seen:
            return "", "duplicate path ordering"
        seen.add(key)
        rendered.append(f"{expression} {term.direction}")

    for column, alias in zip(plan.group_identity, group_aliases):
        if column.casefold() in ordered_groups:
            continue
        expression = f"b.{alias}" if include_zero else alias
        rendered.append(f"{expression} ASC")
    return ", ".join(rendered), None


def _render_zero_path_distinct_count_plan(
    ir: QueryIR,
    plan: PathDistinctCountPlan,
    target_table: str,
) -> Tuple[Optional[str], str, float, GenerationEvidence]:
    """Render a subject baseline left-joined to distinct target counts."""
    path_tables = {
        step.to_table.casefold()
        for step in plan.path_steps
    }
    rendered_path_conditions, condition_error = _render_path_conditions(plan, path_tables)
    if condition_error is not None:
        return _render_plan_failure(condition_error)
    raw_conditions = (
        ir.conditions
        if isinstance(ir.conditions, list)
        else [ir.conditions]
    )
    subject_conditions = [
        _qualify_subject_condition(condition, plan.subject_table)
        for condition in raw_conditions
        if condition.strip()
    ]
    group_aliases = [f"_group_{index}" for index in range(len(plan.group_identity))]
    target_aliases = [f"_target_{index}" for index in range(len(plan.target_identity))]
    group_projection = [
        f"{plan.subject_table}.{column} AS {alias}"
        for column, alias in zip(plan.group_identity, group_aliases)
    ]
    target_projection = [
        f"{target_table}.{column} AS {alias}"
        for column, alias in zip(plan.target_identity, target_aliases)
    ]

    baseline_conditions = [*subject_conditions]
    baseline_conditions.extend(
        f"{plan.subject_table}.{column} IS NOT NULL"
        for column in plan.group_identity
    )
    baseline_sql = (
        f"SELECT DISTINCT {', '.join(group_projection)}\n"
        f"FROM {plan.subject_table}"
    )
    if baseline_conditions:
        baseline_sql += "\nWHERE " + " AND ".join(baseline_conditions)

    pair_sql = (
        f"SELECT DISTINCT {', '.join([*group_projection, *target_projection])}\n"
        f"FROM {plan.subject_table}"
    )
    for step in plan.path_steps:
        conditions = " AND ".join(
            f"{step.from_table}.{from_column} = {step.to_table}.{to_column}"
            for from_column, to_column in step.column_pairs
        )
        pair_sql += f"\nJOIN {step.to_table} ON {conditions}"
    pair_conditions = [*subject_conditions]
    pair_conditions.extend(rendered_path_conditions)
    pair_conditions.extend(
        f"{plan.subject_table}.{column} IS NOT NULL"
        for column in plan.group_identity
    )
    pair_conditions.extend(
        f"{target_table}.{column} IS NOT NULL"
        for column in plan.target_identity
    )
    if pair_conditions:
        pair_sql += "\nWHERE " + " AND ".join(pair_conditions)

    count_sql = (
        f"SELECT {', '.join(group_aliases)}, COUNT(*) AS count\n"
        f"FROM (\n"
        + "\n".join(f"    {line}" for line in pair_sql.splitlines())
        + "\n) AS _distinct_targets\n"
        f"GROUP BY {', '.join(group_aliases)}"
    )
    join_conditions = " AND ".join(
        f"b.{alias} = c.{alias}" for alias in group_aliases
    )
    select_groups = ", ".join(f"b.{alias}" for alias in group_aliases)
    ordering_sql, ordering_error = _render_path_orderings(
        plan,
        group_aliases,
        include_zero=True,
    )
    if ordering_error is not None:
        return _render_plan_failure(ordering_error)
    sql = (
        f"SELECT {select_groups}, COALESCE(c.count, 0) AS count\n"
        f"FROM (\n"
        + "\n".join(f"    {line}" for line in baseline_sql.splitlines())
        + "\n) AS b\n"
        "LEFT JOIN (\n"
        + "\n".join(f"    {line}" for line in count_sql.splitlines())
        + f"\n) AS c ON {join_conditions}"
    )
    if ordering_sql:
        sql += f"\nORDER BY {ordering_sql}"

    explanation_parts = [
        "聚合: COUNT(*) AS count",
        f"表: {plan.subject_table}",
        f"分组: {', '.join(group_aliases)}",
        "包含零计数",
    ]
    if ordering_sql:
        explanation_parts.append(f"排序: {ordering_sql}")
    evidence = ir.evidence
    evidence.items.append(EvidenceItem("base", "Base confidence for zero-count distinct targets", 0.5))
    evidence.items.append(EvidenceItem(
        EVIDENCE_AGGREGATION_PRESENT,
        "Derived distinct target count including zero-count subjects",
        0.15,
        detail=", ".join(plan.target_identity),
    ))
    evidence.items.append(EvidenceItem(
        EVIDENCE_GROUP_BY,
        f"Subject identity groups: {', '.join(group_aliases)}",
        0.1,
    ))
    if subject_conditions or rendered_path_conditions:
        explanation_parts.append(
            f"条件: {len(subject_conditions) + len(rendered_path_conditions)}个"
        )
        evidence.items.append(EvidenceItem(
            EVIDENCE_CONDITIONS_PRESENT,
            "Subject predicates restrict zero-count baseline and target counts",
            0.1,
        ))
    if ir.limit is not None:
        sql = add_limit(sql, ir.limit, ir.dialect)
        explanation_parts.append(f"限制: {ir.limit}条")
        evidence.items.append(EvidenceItem(
            EVIDENCE_LIMIT,
            f"Explicit limit: {ir.limit}",
            0.1,
            detail=str(ir.limit),
        ))
    sql = f"-- Generated for {ir.dialect.upper()}\n{sql}"
    sql = apply_dialect_adjustments(sql, ir.dialect)
    parse_adjustment = validate_sql(sql, ir.dialect)
    if parse_adjustment > 0:
        evidence.items.append(EvidenceItem(
            EVIDENCE_PARSE_OK,
            "Target dialect parser accepted the generated SQL",
            parse_adjustment,
        ))
    elif parse_adjustment < 0:
        evidence.items.append(EvidenceItem(
            EVIDENCE_PARSE_FAIL,
            "Target dialect parser rejected the generated SQL",
            parse_adjustment,
        ))
        return None, (
            "Generated SQL failed target-dialect validation: "
            + " | ".join(explanation_parts)
        ), 0.0, evidence
    return sql, " | ".join(explanation_parts), evidence.score, evidence


def _render_path_distinct_count_plan(
    ir: QueryIR,
) -> Tuple[Optional[str], str, float, GenerationEvidence]:
    """Render a bounded inner-join path and count distinct terminal targets."""
    plan: PathDistinctCountPlan = ir.path_distinct_count_plan  # type: ignore[assignment]
    if ir.operation != "SELECT":
        return _render_plan_failure("only SELECT operations are supported")
    if ir.joins or ir.aggregations or ir.distinct:
        return _render_plan_failure("joins, aggregations, and DISTINCT are unsupported")
    if ir.ordering or ir.orderings:
        return _render_plan_failure("path ordering must use path_orderings")
    if not 1 <= len(plan.path_steps) <= 2:
        return _render_plan_failure("one or two path steps are required")
    if not _safe_identifier(plan.subject_table) or plan.subject_table != ir.table:
        return _render_plan_failure("subject table is invalid")
    if not plan.group_identity or not plan.target_identity:
        return _render_plan_failure("group and target identities are required")
    if any(not _safe_identifier(column) for column in (*plan.group_identity, *plan.target_identity)):
        return _render_plan_failure("identity columns are invalid")

    table_names = [plan.subject_table]
    for step in plan.path_steps:
        if (
            not _safe_identifier(step.from_table)
            or not _safe_identifier(step.to_table)
            or step.from_table != table_names[-1]
            or not step.column_pairs
            or any(
                not _safe_identifier(column)
                for pair in step.column_pairs
                for column in pair
            )
        ):
            return _render_plan_failure("path step is invalid")
        table_names.append(step.to_table)
    if len(set(name.casefold() for name in table_names)) != len(table_names):
        return _render_plan_failure("path repeats a table")
    target_table = table_names[-1]
    if plan.include_zero:
        return _render_zero_path_distinct_count_plan(ir, plan, target_table)
    rendered_path_conditions, condition_error = _render_path_conditions(
        plan,
        {name.casefold() for name in table_names[1:]},
    )
    if condition_error is not None:
        return _render_plan_failure(condition_error)

    inner_projection = [
        f"{plan.subject_table}.{column} AS _group_{index}"
        for index, column in enumerate(plan.group_identity)
    ] + [
        f"{target_table}.{column} AS _target_{index}"
        for index, column in enumerate(plan.target_identity)
    ]
    inner_sql = f"SELECT DISTINCT {', '.join(inner_projection)}\nFROM {plan.subject_table}"
    for step in plan.path_steps:
        conditions = " AND ".join(
            f"{step.from_table}.{from_column} = {step.to_table}.{to_column}"
            for from_column, to_column in step.column_pairs
        )
        inner_sql += f"\nJOIN {step.to_table} ON {conditions}"

    conditions = ir.conditions
    inner_conditions = (
        [_qualify_subject_condition(condition, plan.subject_table) for condition in conditions if condition.strip()]
        if isinstance(conditions, list)
        else ([_qualify_subject_condition(conditions, plan.subject_table)] if conditions.strip() else [])
    )
    inner_conditions.extend(rendered_path_conditions)
    if plan.exclude_null_identity:
        inner_conditions.extend(
            f"{plan.subject_table}.{column} IS NOT NULL"
            for column in plan.group_identity
        )
        inner_conditions.extend(
            f"{target_table}.{column} IS NOT NULL"
            for column in plan.target_identity
        )
    if inner_conditions:
        inner_sql += "\nWHERE " + " AND ".join(inner_conditions)
    indented_inner = "\n".join(f"    {line}" for line in inner_sql.splitlines())

    group_aliases = [f"_group_{index}" for index in range(len(plan.group_identity))]
    select_clause = ", ".join([*group_aliases, "COUNT(*) AS count"])
    sql = (
        f"SELECT {select_clause}\n"
        f"FROM (\n{indented_inner}\n) AS _distinct_targets\n"
        f"GROUP BY {', '.join(group_aliases)}"
    )
    ordering_sql, ordering_error = _render_path_orderings(
        plan,
        group_aliases,
        include_zero=False,
    )
    if ordering_error is not None:
        return _render_plan_failure(ordering_error)
    if ordering_sql:
        sql += f"\nORDER BY {ordering_sql}"
    explanation_parts = ["聚合: COUNT(*) AS count", f"表: {plan.subject_table}", f"分组: {', '.join(group_aliases)}"]
    if ordering_sql:
        explanation_parts.append(f"排序: {ordering_sql}")
    evidence = ir.evidence
    evidence.items.append(EvidenceItem("base", "Base confidence for multi-hop distinct count", 0.5))
    evidence.items.append(EvidenceItem(
        EVIDENCE_AGGREGATION_PRESENT,
        "Derived multi-hop distinct entity count",
        0.15,
        detail=", ".join(plan.target_identity),
    ))
    evidence.items.append(EvidenceItem(
        EVIDENCE_GROUP_BY,
        f"GROUP BY clause: {', '.join(group_aliases)}",
        0.1,
    ))
    if inner_conditions and (conditions or rendered_path_conditions):
        condition_count = (
            len(conditions) if isinstance(conditions, list) else (1 if conditions else 0)
        ) + len(rendered_path_conditions)
        explanation_parts.append(
            f"条件: {condition_count}个"
        )
        evidence.items.append(EvidenceItem(
            EVIDENCE_CONDITIONS_PRESENT,
            "Subject predicates in multi-hop derived count input",
            0.1,
        ))
    if ir.limit is not None:
        sql = add_limit(sql, ir.limit, ir.dialect)
        explanation_parts.append(f"限制: {ir.limit}条")
        evidence.items.append(EvidenceItem(
            EVIDENCE_LIMIT,
            f"Explicit limit: {ir.limit}",
            0.1,
            detail=str(ir.limit),
        ))
    sql = f"-- Generated for {ir.dialect.upper()}\n{sql}"
    sql = apply_dialect_adjustments(sql, ir.dialect)
    parse_adjustment = validate_sql(sql, ir.dialect)
    if parse_adjustment > 0:
        evidence.items.append(EvidenceItem(
            EVIDENCE_PARSE_OK,
            "Target dialect parser accepted the generated SQL",
            parse_adjustment,
        ))
    elif parse_adjustment < 0:
        evidence.items.append(EvidenceItem(
            EVIDENCE_PARSE_FAIL,
            "Target dialect parser rejected the generated SQL",
            parse_adjustment,
        ))
        return None, (
            "Generated SQL failed target-dialect validation: "
            + " | ".join(explanation_parts)
        ), 0.0, evidence
    return sql, " | ".join(explanation_parts), evidence.score, evidence


# ── Renderer ────────────────────────────────────────────────────────────────

def render_sql(ir: QueryIR) -> Tuple[Optional[str], str, float, GenerationEvidence]:
    """Build SQL statement from the Query IR.

    Fail-closed: any join entry with ``condition is None`` (an
    unresolved/unknown relationship) immediately returns
    ``(None, explanation, 0.0, GenerationEvidence())`` so the caller
    observes ``success=False``.  The relationship is never silently
    dropped.

    Returns the same 4-tuple the legacy ``_build_sql_enhanced`` returns:
    ``(sql, explanation, confidence, evidence)``.
    """
    if ir.path_distinct_count_plan is not None and ir.distinct_count_plan is not None:
        return _render_plan_failure("multiple derived count plans are unsupported")
    if ir.path_distinct_count_plan is not None:
        return _render_path_distinct_count_plan(ir)
    if ir.distinct_count_plan is not None:
        return _render_distinct_count_plan(ir)

    for join in ir.joins:
        if join.get("path"):
            continue
        if join.get("condition") is None:
            subject = join.get("subject") or ir.table
            pair_desc = f"{subject} ⟷ {join['table']}"
            explanation = (
                "Unable to safely infer the relationship between the "
                f"table(s) involved ({pair_desc}). Please provide the "
                "join condition or schema relationship."
            )
            return None, explanation, 0.0, GenerationEvidence()

    operation = ir.operation
    table = ir.table
    columns = ir.columns
    conditions = ir.conditions
    aggregations = ir.aggregations
    group_by = ir.group_by
    ordering = ir.ordering
    limit = ir.limit
    joins = ir.joins
    distinct = ir.distinct
    dialect = ir.dialect

    explanation_parts: list[str] = []
    evidence = ir.evidence
    evidence.items.append(EvidenceItem("base", "Base confidence for generated SQL", 0.5))

    if operation == "SELECT":
        distinct_kw = "DISTINCT " if distinct else ""
        if aggregations:
            if group_by:
                select_parts = group_by + aggregations
                select_clause = ", ".join(select_parts)
            else:
                select_clause = ", ".join(aggregations)
            explanation_parts.append(f"聚合: {', '.join(aggregations)}")
            evidence.items.append(EvidenceItem(
                EVIDENCE_AGGREGATION_PRESENT,
                f"Explicit aggregation requested: {', '.join(aggregations)}",
                0.15, detail=aggregations[0],
            ))
        else:
            select_clause = ", ".join(columns)
            if columns != ["*"]:
                explanation_parts.append(f"列: {', '.join(columns)}")
                evidence.items.append(EvidenceItem(
                    EVIDENCE_COLUMNS_EXPLICIT,
                    "Explicit columns requested", 0.1,
                    detail=columns[0],
                ))
        sql = f"SELECT {distinct_kw}{select_clause}\nFROM {table}"
        explanation_parts.append(f"表: {table}")
        if table != "table_name":
            evidence.items.append(EvidenceItem(
                EVIDENCE_TABLE_KNOWN,
                f"Table resolved to known name: {table}", 0.2,
                detail=table,
            ))
        relational_where_open = False
        for join in joins:
            # Join conditions are only ever emitted from a resolved
            # canonical relationship (G1). Unresolved pairs are blocked
            # upstream by generate(); keep a structural guard so a join
            # can never be composed with a missing condition.
            if join.get("condition") is None:
                continue
            if join.get("relational"):
                # EXISTS/NOT EXISTS: preserves row count, no duplicates.
                # Multiple relational EXISTS clauses compose into ONE WHERE:
                # the first gets its own WHERE, the rest append with AND,
                # mirroring standard SQL 'WHERE EXISTS (...) AND EXISTS (...)'.
                if join.get("path"):
                    path = join["path"]
                    subquery = f"SELECT 1\n    FROM {path[0]['table']}\n    WHERE {path[0]['condition']}"
                    indent = "    "
                    for step in path[1:]:
                        subquery += (
                            f"\n    AND EXISTS (\n    {indent}SELECT 1\n"
                            f"    {indent}FROM {step['table']}\n"
                            f"    {indent}WHERE {step['condition']}\n    {indent})"
                        )
                        indent += "    "
                else:
                    subquery = f"SELECT 1\n    FROM {join['table']}\n    WHERE {join['condition']}"
                # Merge date conditions into subquery if present
                if conditions:
                    cond_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
                    subquery += f"\n    AND {cond_sql}"
                    conditions = []  # Remove from top-level conditions
                clause = (
                    f"NOT EXISTS (\n    {subquery}\n)"
                    if join["type"] == "NOT EXISTS"
                    else f"EXISTS (\n    {subquery}\n)"
                )
                if relational_where_open:
                    sql += f"\nAND {clause}"
                else:
                    sql += f"\nWHERE {clause}"
                    relational_where_open = True
                explanation_parts.append(
                    "关联: {} ({})".format(join["table"], join["type"])
                )
                evidence.items.append(EvidenceItem(
                    EVIDENCE_JOIN_KNOWN,
                    f"Known relationship: {join['subject']} → {join['table']}",
                    0.1, detail=join["condition"],
                ))
            else:
                # Physical JOIN — kind comes from the structured JoinSpec
                # (LEFT/RIGHT/INNER/OUTER), never a first-token guess.
                sql += f"\n{join_sql_kind(join)} JOIN {join['table']} ON {join['condition']}"
                explanation_parts.append(f"关联: {join['table']}")
                evidence.items.append(EvidenceItem(
                    EVIDENCE_JOIN_KNOWN,
                    f"Physical join: {join['table']} ON {join['condition']}",
                    0.1, detail=join["condition"],
                ))
        # If relational EXISTS clauses already opened a WHERE, any remaining
        # top-level conditions attach with AND instead of a second WHERE.
        if conditions:
            condition_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
            if relational_where_open:
                sql += f"\nAND {condition_sql}"
            else:
                sql += f"\nWHERE {condition_sql}"
            count = len(conditions) if not isinstance(conditions, str) else 1
            explanation_parts.append(f"条件: {count}个")
            evidence.items.append(EvidenceItem(
                EVIDENCE_CONDITIONS_PRESENT,
                f"{count} explicit predicate(s) in WHERE clause",
                0.1,
            ))
        if group_by:
            sql += f"\nGROUP BY {', '.join(group_by)}"
            explanation_parts.append(f"分组: {', '.join(group_by)}")
            evidence.items.append(EvidenceItem(
                EVIDENCE_GROUP_BY,
                f"GROUP BY clause: {', '.join(group_by)}", 0.1,
            ))
        elif aggregations and columns != ["*"]:
            group_cols = [c for c in columns if c != "*"]
            if group_cols:
                sql += f"\nGROUP BY {', '.join(group_cols)}"
        if ir.aggregate_orderings is not None and (ordering or ir.orderings):
            return _render_plan_failure("generic and aggregate orderings cannot be combined")
        aggregate_ordering_sql = ""
        if ir.aggregate_orderings:
            if len(aggregations) != 1:
                return _render_plan_failure("aggregate ordering requires one COUNT(DISTINCT pk) aggregation")
            match = re.fullmatch(
                r"COUNT\(DISTINCT\s+([A-Za-z_][A-Za-z0-9_$]*)\)\s+AS\s+count",
                aggregations[0], re.IGNORECASE,
            )
            if match is None:
                return _render_plan_failure("aggregate ordering requires COUNT(DISTINCT pk) AS count")
            count_expression = f"COUNT(DISTINCT {match.group(1)})"
            aggregate_ordering_sql, ordering_error = _render_aggregate_orderings(
                ir.aggregate_orderings, group_by, count_expression
            )
            if ordering_error is not None:
                return _render_plan_failure(ordering_error)
            explanation_parts.append(f"排序: {aggregate_ordering_sql}")
        active_orderings = ir.orderings or ([ordering] if ordering else [])
        if ir.aggregate_orderings is None and active_orderings:
            ordering_sql = ", ".join(
                f"{column} {direction}" for column, direction in active_orderings
            )
            sql += f"\nORDER BY {ordering_sql}"
            explanation_parts.append(f"排序: {ordering_sql}")
        elif aggregate_ordering_sql:
            sql += f"\nORDER BY {aggregate_ordering_sql}"
        if limit is not None:
            sql = add_limit(sql, limit, dialect)
            explanation_parts.append(f"限制: {limit}条")
            evidence.items.append(EvidenceItem(
                EVIDENCE_LIMIT,
                f"Explicit limit: {limit}", 0.1, detail=str(limit),
            ))
    elif operation == "INSERT":
        cols = columns if columns != ["*"] else ["col1", "col2"]
        placeholders = ", ".join(
            parameter_placeholder(index, dialect)
            for index in range(1, len(cols) + 1)
        )
        sql = f"INSERT INTO {table} ({', '.join(cols)})\nVALUES ({placeholders})"
        explanation_parts.append(f"插入到: {table}")
    elif operation == "UPDATE":
        update_cols = columns if columns != ["*"] else ["column"]
        set_clause = ", ".join(
            f"{c} = {parameter_placeholder(index, dialect)}"
            for index, c in enumerate(update_cols, start=1)
        )
        sql = f"UPDATE {table}\nSET {set_clause}"
        if conditions:
            condition_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
            sql += f"\nWHERE {condition_sql}"
        else:
            sql += f"\nWHERE id = {parameter_placeholder(len(update_cols) + 1, dialect)}"
        explanation_parts.append(f"更新: {table}")
    elif operation == "DELETE":
        sql = f"DELETE FROM {table}"
        if conditions:
            condition_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
            sql += f"\nWHERE {condition_sql}"
        else:
            sql += f"\nWHERE id = {parameter_placeholder(1, dialect)}"
        explanation_parts.append(f"删除: {table}")
    else:
        sql = f"-- 无法解析: {operation}"
        # Unknown operation — clear all evidence; score will be 0.0.
        evidence = GenerationEvidence()

    sql = f"-- Generated for {dialect.upper()}\n{sql}"
    sql = apply_dialect_adjustments(sql, dialect)
    parse_adjustment = validate_sql(sql, dialect)
    if parse_adjustment > 0:
        evidence.items.append(EvidenceItem(
            EVIDENCE_PARSE_OK,
            "Target dialect parser accepted the generated SQL",
            parse_adjustment,
        ))
    elif parse_adjustment < 0:
        evidence.items.append(EvidenceItem(
            EVIDENCE_PARSE_FAIL,
            "Target dialect parser rejected the generated SQL",
            parse_adjustment,
        ))
        # A generated statement that the target parser rejects must never be
        # advertised as a successful/executable result.  Keep the invariant
        # ``sql is None iff success is False`` used by API and UI consumers.
        return None, (
            "Generated SQL failed target-dialect validation: "
            + " | ".join(explanation_parts)
        ), 0.0, evidence
    confidence = evidence.score
    return sql, " | ".join(explanation_parts), confidence, evidence
