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
from .ir import QueryIR
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
    for join in ir.joins:
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
        if ordering:
            sql += f"\nORDER BY {ordering[0]} {ordering[1]}"
            explanation_parts.append(f"排序: {ordering[0]} {ordering[1]}")
        if limit:
            sql = add_limit(sql, limit, dialect)
            explanation_parts.append(f"限制: {limit}条")
            evidence.items.append(EvidenceItem(
                EVIDENCE_LIMIT,
                f"Explicit limit: {limit}", 0.1, detail=str(limit),
            ))
    elif operation == "INSERT":
        cols = columns if columns != ["*"] else ["col1", "col2"]
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT INTO {table} ({', '.join(cols)})\nVALUES ({placeholders})"
        explanation_parts.append(f"插入到: {table}")
    elif operation == "UPDATE":
        update_cols = columns if columns != ["*"] else ["column"]
        set_clause = ", ".join([f"{c} = ?" for c in update_cols])
        sql = f"UPDATE {table}\nSET {set_clause}"
        if conditions:
            condition_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
            sql += f"\nWHERE {condition_sql}"
        else:
            sql += "\nWHERE id = ?"
        explanation_parts.append(f"更新: {table}")
    elif operation == "DELETE":
        sql = f"DELETE FROM {table}"
        if conditions:
            condition_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
            sql += f"\nWHERE {condition_sql}"
        else:
            sql += "\nWHERE id = ?"
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
    confidence = evidence.score
    return sql, " | ".join(explanation_parts), confidence, evidence
