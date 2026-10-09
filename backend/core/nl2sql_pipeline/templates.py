#!/usr/bin/env python3
"""P8 NL2SQL pipeline: template generation (moved from nl2sql_legacy).

Contains the per-template SQL string builder (``generate_from_template``)
and its helper (``template_suggestions``).  Bodies are verbatim from
``nl2sql_legacy._generate_from_template`` and
``nl2sql_legacy._generate_suggestions_for_template``; they now call the
pure stage functions from ``renderer`` / ``dialect`` / ``validation``
/ ``predicates`` / ``resolution`` / ``relations`` directly.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from ..nl2sql_components.evidence import (
    EVIDENCE_AGGREGATION_PRESENT,
    EVIDENCE_CONDITIONS_PRESENT,
    EVIDENCE_GROUP_BY,
    EVIDENCE_JOIN_KNOWN,
    EVIDENCE_LIMIT,
    EVIDENCE_PARSE_FAIL,
    EVIDENCE_PARSE_OK,
    EVIDENCE_TABLE_KNOWN,
    EVIDENCE_TEMPLATE_MATCHED,
    EvidenceItem,
    GenerationEvidence,
)
from ..nl2sql_components.mappings import COLUMN_PATTERNS, TABLE_PATTERNS
from ..nl2sql_components.templates import QueryTemplate
from .dialect import apply_dialect_adjustments
from .models import NL2SQLResult
from .predicates import extract_conditions as extract_conditions_impl
from .renderer import add_limit, join_sql_kind
from .resolution import extract_joins, extract_table_subject
from .validation import validate_sql

logger = logging.getLogger(__name__)


def generate_from_template(
    template: QueryTemplate,
    match_groups: Dict[str, Any],
    analysis: Dict[str, Any],
    dialect: str,
    table_hint: Optional[str],
    column_hints: Optional[List[str]],
    text_lower: str = "",
    text_original: str = "",
    table_patterns: Optional[Dict[str, str]] = None,
    column_patterns: Optional[Dict[str, str]] = None,
) -> NL2SQLResult:
    """Generate SQL from a matched template.

    Accumulates a structured GenerationEvidence trail whose weights
    mirror the legacy heuristic exactly so the final score is
    unchanged while the items explain it.
    """
    table_patterns = table_patterns or TABLE_PATTERNS
    column_patterns = column_patterns or COLUMN_PATTERNS

    explanation_parts = []
    table = table_hint or (
        analysis["tables"][0] if analysis["tables"] else "table_name"
    )
    columns = column_hints or analysis["columns"] or ["*"]
    numbers = analysis["numbers"]
    # Structured evidence trail; weights mirror the heuristic exactly.
    evidence = GenerationEvidence()
    evidence.items.append(
        EvidenceItem("base", "Base confidence for template match", 0.7)
    )
    if table != "table_name":
        evidence.items.append(EvidenceItem(
            EVIDENCE_TABLE_KNOWN,
            f"Table resolved to known name: {table}", 0.1, detail=table,
        ))
    # The clause-aware merge below combines the branch's own predicates
    # with any template-external time/status condition without duplicating
    # a clause the branch owns. The extractor must see the full original
    # text for number extraction: the template capture alone silently
    # drops conditions that sit outside the captured window.
    external_conditions = extract_conditions_impl(
        text_lower, text_original or text_lower, column_patterns
    )

    try:
        if template.name == "top_n_query":
            n = numbers[0] if numbers else "10"
            order_col = analysis["columns"][0] if analysis["columns"] else "id"
            # Determine ordering direction based on request text
            request_text = str((match_groups or {}).get("match", "")).lower()
            ascending_requested = bool(
                re.search(r"\b(bottom|lowest|smallest)\b|最低|最少", request_text)
            )
            order_dir = "ASC" if ascending_requested else "DESC"
            if ascending_requested:
                explanation_parts.append(f"查询最低/最少{n}条记录")
            else:
                explanation_parts.append(f"查询前{n}条记录")
            # Clause order is semantic: WHERE before ORDER BY before LIMIT.
            # The legacy top_n branch composed ORDER BY + LIMIT first and
            # then a clause-aware merge re-appended WHERE *after* LIMIT,
            # producing unparseable 'LIMIT N\nWHERE ...' output.
            external_where_parts = [
                c for c in external_conditions
                if "DATE_SUB" not in c and "ADD_MONTHS" not in c and "DATE_ADD" not in c
            ]
            base_sql = f"SELECT *\nFROM {table}"
            if external_where_parts:
                base_sql += f"\nWHERE {' AND '.join(external_where_parts)}"
            base_sql += f"\nORDER BY {order_col} {order_dir}"
            sql = add_limit(base_sql, int(n), dialect)
            evidence.items.append(EvidenceItem(
                EVIDENCE_LIMIT,
                f"Template limit applied: {n}", 0.1, detail=str(n),
            ))
        elif template.name == "count_by_group":
            group_col = (
                analysis["columns"][0] if analysis["columns"] else "category"
            )
            sql = (
                f"SELECT {group_col}, COUNT(*) AS count\n"
                f"FROM {table}\nGROUP BY {group_col}"
            )
            explanation_parts.append(f"按{group_col}分组统计")
            evidence.items.append(EvidenceItem(
                EVIDENCE_GROUP_BY,
                f"Template GROUP BY on {group_col}", 0.1, detail=group_col,
            ))
        elif template.name == "time_range_query":
            # The canonical D3 semantic expression is the single source of
            # the date predicate. Other external conditions (comparisons,
            # status flags) stay template-external and are composed by the
            # clause-aware merge below, which de-duplicates instead of
            # re-appending a second WHERE.
            n = numbers[0] if numbers else "7"
            # Preserve the requested unit: the time_range template captures
            # the unit group (days?/weeks?/months?/years? or 天/周/月/年)
            # but the legacy explanation hard-coded 天, reporting a weeks
            # or months request as days. The unit flows from the original
            # text, never from the captured number alone.
            unit_source = str((match_groups or {}).get("unit", ""))
            if not unit_source:
                # Unnamed-group capture: re-locate the unit word in the
                # matched window.
                m = re.search(
                    r"(天|周|月|年|days?|weeks?|months?|years?)\s*(?:的|内的)?\s*$|"
                    r"(天|周|月|年|days?|weeks?|months?|years?)",
                    str((match_groups or {}).get("match", "")),
                    re.IGNORECASE,
                )
                unit_source = (m.group(1) or m.group(2)) if m else ""
            unit = (
                "周" if "week" in unit_source.lower() or "周" in unit_source
                else "月" if ("month" in unit_source.lower() or "月" in unit_source)
                else "年" if ("year" in unit_source.lower() or "年" in unit_source)
                else "天"
            )
            date_col = (
                "created_at"
                if "created_at" in str(analysis["columns"])
                else "date"
            )
            date_predicate = None
            for c in external_conditions:
                if "DATE_SUB" in c or "ADD_MONTHS" in c or "DATE_ADD" in c:
                    date_predicate = c
                    break
            if date_predicate is None:
                date_predicate = f"{date_col} >= DATE_SUB(CURRENT_DATE, {n})"
            sql = f"SELECT *\nFROM {table}\nWHERE {date_predicate}"
            explanation_parts.append(f"查询最近{n}{unit}数据")
            evidence.items.append(EvidenceItem(
                EVIDENCE_CONDITIONS_PRESENT,
                f"Template time range: {date_predicate}", 0.1, detail=table,
            ))
        elif template.name == "aggregate_query":
            agg_func = "COUNT"
            for token in analysis["tokens"]:
                if token in ["平均", "average", "avg"]:
                    agg_func = "AVG"
                elif token in ["总和", "sum", "合计"]:
                    agg_func = "SUM"
                elif token in ["最大", "max", "maximum"]:
                    agg_func = "MAX"
                elif token in ["最小", "min", "minimum"]:
                    agg_func = "MIN"
            col = analysis["columns"][0] if analysis["columns"] else "*"
            sql = f"SELECT {agg_func}({col}) AS result\nFROM {table}"
            explanation_parts.append(f"计算{agg_func}({col})")
            evidence.items.append(EvidenceItem(
                EVIDENCE_AGGREGATION_PRESENT,
                f"Template aggregation: {agg_func}({col})", 0.1, detail=agg_func,
            ))
        elif template.name == "condition_query":
            col = analysis["columns"][0] if analysis["columns"] else "column"
            value = numbers[0] if numbers else "0"
            op = "="
            for token in analysis["tokens"]:
                if token in ["大于", "超过", "greater", ">"]:
                    op = ">"
                elif token in ["小于", "低于", "less", "<"]:
                    op = "<"
                elif token in ["不等于", "!="]:
                    op = "!="
                elif token in ["大于等于", ">="]:
                    op = ">="
                elif token in ["小于等于", "<="]:
                    op = "<="
            condition_predicate = f"{col} {op} {value}"
            # Fold in template-external conditions that are not already
            # implied by the branch's own comparison. Date predicates are
            # recognised by their canonical D3 forms; any other external
            # condition (status, flags) is appended verbatim.
            sql = f"SELECT *\nFROM {table}\nWHERE {condition_predicate}"
            for c in external_conditions:
                if c in sql:
                    continue
                if "DATE_SUB" not in c and "ADD_MONTHS" not in c:
                    sql += f"\nAND {c}"
            explanation_parts.append(f"条件: {col} {op} {value}")
            evidence.items.append(EvidenceItem(
                EVIDENCE_CONDITIONS_PRESENT,
                f"Template condition: {col} {op} {value}", 0.1,
            ))
        elif template.name == "join_query":
            # JOIN composition is owned by the enhanced path: route every
            # join request through resolution.extract_joins, which only
            # yields a canonical condition for known relationships. The
            # template must not invent a condition of its own.
            all_joins = extract_joins(text_lower, table_patterns)
            joins = [j for j in all_joins if j["condition"] is not None]
            # The join request is only safe when every pair the text names
            # has a canonical relationship; otherwise fail the request.
            pairs_blocked = [j for j in all_joins if j["condition"] is None]
            if pairs_blocked:
                blocked = " ⟷ ".join(
                    [j["subject"] for j in pairs_blocked]
                    + [j["table"] for j in pairs_blocked]
                )
                return NL2SQLResult(
                    success=False,
                    input_text=match_groups.get("match", ""),
                    sql=None,
                    dialect=dialect,
                    explanation=(
                        "Unable to safely infer the relationship between the "
                        f"table(s) involved ({blocked}). Please provide the "
                        "join condition or schema relationship."
                    ),
                    confidence=0.0,
                    evidence=GenerationEvidence(),
                    suggestions=[
                        "Specify the relationship between tables, "
                        "e.g., 'users.id = invoices.user_id'"
                    ],
                    parsed_elements=analysis,
                )
            if joins:
                subject = extract_table_subject(text_lower, table_patterns)
                sql = f"SELECT *\nFROM {subject or joins[0]['table']}"
                for join in joins:
                    # Emit the structured join kind from JoinSpec when
                    # the user asked for a physical join (LEFT/RIGHT/
                    # INNER/OUTER); an unqualified join stays INNER.
                    kind = join_sql_kind(join)
                    sql += f"\n{kind} JOIN {join['table']} ON {join['condition']}"
                    explanation_parts.append(
                        f"关联: {subject or joins[0]['table']} ⟷ {join['table']}"
                    )
                    evidence.items.append(EvidenceItem(
                        EVIDENCE_JOIN_KNOWN,
                        f"Join in template: {join['table']} ON {join['condition']}",
                        0.15, detail=join["condition"],
                    ))
            else:
                # No known pair resolvable — fail-safe too.
                return NL2SQLResult(
                    success=False,
                    input_text=match_groups.get("match", ""),
                    sql=None,
                    dialect=dialect,
                    explanation=(
                        "Unable to safely infer the relationship between the "
                        "table(s). Please provide the join condition or "
                        "schema relationship."
                    ),
                    confidence=0.0,
                    evidence=GenerationEvidence(),
                    suggestions=[
                        "Specify the relationship between tables, "
                        "e.g., 'users.id = invoices.user_id'"
                    ],
                    parsed_elements=analysis,
                )
        elif template.name == "select_with_columns":
            cols = ", ".join(columns) if columns != ["*"] else "*"
            sql = f"SELECT {cols}\nFROM {table}"
            explanation_parts.append(f"查询: {cols}")
        else:
            sql = f"SELECT *\nFROM {table}"
            explanation_parts.append(f"查询表: {table}")

        # Clause-aware predicate composition: add only the time/status
        # conditions the composed SQL does not already carry. Branches
        # that own their WHERE clause (time_range/condition) already
        # folded the external conditions in above; this step then
        # de-duplicates instead of appending a second WHERE.
        merged_conditions: List[str] = []
        for c in external_conditions:
            base = c.split(" AND ")[0] if " AND " in c else c
            base = base.strip()
            if base in sql or c in sql:
                continue
            # top_n folded its own external conditions into WHERE above;
            # never re-append them here as a second WHERE.
            if template.name == "top_n_query" and "DATE_SUB" not in c and "ADD_MONTHS" not in c and "DATE_ADD" not in c:
                continue
            if not any(
                kw in text_lower
                for kw in [
                    "today", "yesterday", "tomorrow", "last", "past",
                    "本周", "本月", "本年", "今天", "昨天", "明天"
                ]
            ) and c in [
                "status = 'active'", "status = 'inactive'",
                "is_deleted = 1", "is_deleted = 0"
            ]:
                continue
            merged_conditions.append(c)
        if merged_conditions:
            if "WHERE" in sql.upper():
                sql = f"{sql}\nAND {' AND '.join(merged_conditions)}"
            else:
                sql = f"{sql}\nWHERE {' AND '.join(merged_conditions)}"
            explanation_parts.append(f"日期条件: {len(merged_conditions)}个")
            evidence.items.append(EvidenceItem(
                EVIDENCE_CONDITIONS_PRESENT,
                f"Merged {len(merged_conditions)} external condition(s)",
                0.1,
            ))

        sql = f"-- Generated for {dialect.upper()}\n{sql}"
        sql = apply_dialect_adjustments(sql, dialect)
        parse_adjustment = validate_sql(sql, dialect)

        evidence.items.append(EvidenceItem(
            EVIDENCE_TEMPLATE_MATCHED,
            f"Template matched: {template.name}", 0.0, detail=template.name,
        ))
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

        suggestions = template_suggestions(template, table, columns, dialect)

        return NL2SQLResult(
            success=True,
            input_text=match_groups.get("match", ""),
            sql=sql,
            dialect=dialect,
            explanation=" | ".join(explanation_parts),
            confidence=evidence.score,
            evidence=evidence,
            suggestions=suggestions,
            parsed_elements=analysis,
        )
    except Exception as exc:
        logger.warning("Template generation failed: %s", exc)
        return NL2SQLResult(
            success=False,
            input_text=str(match_groups),
            dialect=dialect,
            explanation=f"Template error: {exc}",
            confidence=0.0,
            evidence=GenerationEvidence(),
        )


def template_suggestions(
    template: QueryTemplate,
    table: str,
    columns: List[str],
    dialect: str,
) -> List[str]:
    """Generate suggestions specific to template-based generation."""
    suggestions = []
    if table == "table_name":
        suggestions.append("💡 请指定具体的表名，如：用户表、订单表、员工表")
    if columns == ["*"]:
        suggestions.append("💡 建议指定具体列名以提高查询性能")
    if template.name == "join_query":
        suggestions.append("💡 请确认关联条件是否正确")
    if template.name == "time_range_query" and dialect == "oracle":
        suggestions.append("💡 Oracle 日期函数语法可能需要调整")
    return suggestions
