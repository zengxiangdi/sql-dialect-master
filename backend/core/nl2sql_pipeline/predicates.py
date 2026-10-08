#!/usr/bin/env python3
"""P8 NL2SQL pipeline: predicate extraction (moved from nl2sql_legacy).

``extract_conditions`` is a verbatim move of
``nl2sql_legacy._extract_conditions_enhanced``.  All keyword tables,
IN-predicate parsing, comparison operators, BETWEEN / LIKE / NULL /
date / time / status rules are unchanged; the only difference is that
``COLUMN_PATTERNS`` is now passed as a parameter instead of read from
the instance attribute.
"""
import re
from typing import Dict, List, Optional

from ..nl2sql_components.boolean_conditions import extract_boolean_conditions


def extract_conditions(
    text: str,
    original: str,
    column_patterns: Dict[str, str],
) -> list:
    """Extract WHERE conditions with enhanced parsing including boolean expressions.

    Moved verbatim from ``nl2sql_legacy._extract_conditions_enhanced``.
    ``column_patterns`` replaces ``self.COLUMN_PATTERNS``.
    """
    # Use the structured boolean extractor first — it correctly handles
    # multiple predicates connected by AND/OR while preserving precedence.
    boolean_conditions = extract_boolean_conditions(text)
    if boolean_conditions:
        return boolean_conditions

    conditions = []
    numbers = re.findall(r"\d+\.?\d*", original)
    condition_column = None
    for pattern, column in column_patterns.items():
        if pattern in text:
            condition_column = column
            break

    # Handle IN/NOT IN predicate (must come before generic comparison handling)
    in_matched_columns: set = set()
    in_match = re.search(
        r"\b(\w+)\s+(not\s+)?in\s*\(([^)]+)\)",
        text,
        re.IGNORECASE,
    )
    if in_match:
        col = in_match.group(1)
        negation = in_match.group(2) is not None
        raw_values = in_match.group(3).strip()
        # Parse comma-separated values, preserving quoted strings
        values = []
        current = ""
        quote_char = None
        for char in raw_values:
            if char in ("'", '"'):
                if quote_char and quote_char == char:
                    quote_char = None
                elif not quote_char:
                    quote_char = char
                current += char
            elif char == "," and not quote_char:
                if current.strip():
                    values.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            values.append(current.strip())

        if values:
            formatted_values = ", ".join(
                f"'{v}'" if v.startswith(("'", '"')) or not re.match(r"^-?\d+(\.\d+)?$", v) else v
                for v in values
            )
            operator = "NOT IN" if negation else "IN"
            conditions.append(f"{col} {operator} ({formatted_values})")
            in_matched_columns.add(col.lower())

    comparisons = [
        (["大于等于", "不小于", "至少", "greater than or equal to", "larger than or equal to"], ">="),
        (["小于等于", "不大于", "最多", "less than or equal to", "smaller than or equal to"], "<="),
        (["不等于", "不是", "不为", "not equal", "isn't", "doesn't equal"], "!="),
        (["大于", "超过", "高于", "多于", "greater", "more than", "above", "over", ">"], ">"),
        (["小于", "低于", "少于", "不足", "less", "less than", "below", "under", "<"], "<"),
        (["等于", "是", "为", "equals", "equal", "="], "="),
    ]
    for keywords, op in comparisons:
        if any(keyword in text for keyword in keywords) and numbers:
            col = condition_column or "column"
            conditions.append(f"{col} {op} {numbers[0]}")
            break

    if any(keyword in text for keyword in ["之间", "范围", "between", "from...to"]):
        if len(numbers) >= 2:
            col = condition_column or "column"
            conditions.append(f"{col} BETWEEN {numbers[0]} AND {numbers[1]}")

    if any(keyword in text for keyword in ["包含", "含有", "contains", "like", "includes"]):
        match = re.search(r"[\"']([^\"']+)[\"']", original)
        if match:
            col = condition_column or "column"
            conditions.append(f"{col} LIKE '%{match.group(1)}%'")

    has_negative_null = any(
        keyword in text
        for keyword in ["非空", "不为空", "is not null", "not null", "not empty"]
    )
    if has_negative_null:
        conditions.append(f"{condition_column or 'column'} IS NOT NULL")
    elif any(keyword in text for keyword in ["为空", "空值", "is null", "null", "empty"]):
        conditions.append(f"{condition_column or 'column'} IS NULL")

    date_col = "created_at" if "created_at" in text else "date"
    if "今天" in text or "today" in text:
        conditions.append(f"{date_col} = CURRENT_DATE")
    elif "昨天" in text or "yesterday" in text:
        conditions.append(f"{date_col} = DATE_SUB(CURRENT_DATE, 1)")
    elif "前天" in text or "day before" in text:
        conditions.append(f"{date_col} = DATE_SUB(CURRENT_DATE, 2)")
    elif "明天" in text or "tomorrow" in text:
        conditions.append(f"{date_col} = DATE_ADD(CURRENT_DATE, 1)")

    time_patterns = [
        (r"(最近|过去|last|past)\s*(\d+)\s*(天|day)", "DAY"),
        (r"(最近|过去|last|past)\s*(\d+)\s*(周|week)", "WEEK"),
        (r"(最近|过去|last|past)\s*(\d+)\s*(月|month)", "MONTH"),
        (r"(最近|过去|last|past)\s*(\d+)\s*(年|year)", "YEAR"),
    ]
    for pattern, unit in time_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            n = match.group(2)
            if unit == "DAY":
                conditions.append(f"{date_col} >= DATE_SUB(CURRENT_DATE, {n})")
            elif unit == "WEEK":
                conditions.append(f"{date_col} >= DATE_SUB(CURRENT_DATE, {int(n) * 7})")
            elif unit == "MONTH":
                conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -{n})")
            elif unit == "YEAR":
                conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -{int(n) * 12})")
            break

    # Bare period expressions without explicit count
    if not any(c for c in conditions if "DATE_SUB" in c or "DATE_ADD" in c or "ADD_MONTHS" in c or "CURRENT_DATE" in c):
        if ("last week" in text or "本周" in text) and "this week" not in text and "本周" not in text:
            conditions.append(f"{date_col} >= DATE_SUB(CURRENT_DATE, 7)")
        if "last month" in text:
            conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -1)")
        if "last year" in text:
            conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -12)")

    if "本周" in text or "this week" in text:
        conditions.append(f"WEEKOFYEAR({date_col}) = WEEKOFYEAR(CURRENT_DATE)")
    if "本月" in text or "this month" in text:
        conditions.append(
            f"MONTH({date_col}) = MONTH(CURRENT_DATE) AND YEAR({date_col}) = YEAR(CURRENT_DATE)"
        )
    if "本年" in text or "this year" in text:
        conditions.append(f"YEAR({date_col}) = YEAR(CURRENT_DATE)")

    status_patterns = [
        (["有效", "active", "enabled", "valid"], "status = 'active'"),
        (["无效", "inactive", "disabled", "invalid"], "status = 'inactive'"),
        (["已删除", "deleted", "removed"], "is_deleted = 1"),
        (["未删除", "not deleted"], "is_deleted = 0"),
        (["已完成", "completed", "done", "finished"], "status = 'completed'"),
        (["未完成", "pending", "incomplete"], "status = 'pending'"),
        (["已支付", "paid"], "status = 'paid'"),
        (["未支付", "unpaid"], "status = 'unpaid'"),
    ]
    for keywords, condition in status_patterns:
        # Skip status pattern if the column was already matched via IN predicate
        col_match = re.match(r"^(\w+)\s*=", condition)
        col_name = col_match.group(1).lower() if col_match else None
        if col_name and col_name in in_matched_columns:
            continue
        if any(keyword in text for keyword in keywords):
            conditions.append(condition)
            break
    return conditions
