#!/usr/bin/env python3
"""P8 NL2SQL pipeline: clause extraction (moved from nl2sql_legacy).

Holds the ``extract_group_by`` and ``extract_ordering`` stage functions
(verbatim moves of the legacy instance methods, parameterized on
``COLUMN_PATTERNS`` / ``TABLE_PATTERNS``).  ``extract_limit`` and
``check_distinct`` are re-exports of the stateless ``core_extract``
primitives the legacy class already delegated to.
"""
import re
from typing import Dict, List, Optional, Tuple

from ..nl2sql_components.core_extract import check_distinct, extract_limit
from ..nl2sql_components.mappings import COLUMN_PATTERNS, TABLE_PATTERNS

__all__ = [
    "check_distinct",
    "extract_group_by",
    "extract_limit",
    "extract_ordering",
]


def extract_group_by(
    text: str,
    column_patterns: Optional[Dict[str, str]] = None,
    table_patterns: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Extract GROUP BY columns from text.

    Verbatim move of ``nl2sql_legacy._extract_group_by``; ``column_patterns``
    and ``table_patterns`` replace the instance attributes.
    """
    column_patterns = column_patterns or COLUMN_PATTERNS
    table_patterns = table_patterns or TABLE_PATTERNS
    group_cols: List[str] = []
    patterns = [
        r"按(.+?)(分组|汇总|统计)",
        r"group\s*by\s*(\w+)",
        r"grouped\s*by\s*(\w+)",
        r"per\s+(\w+)",
        r"each\s+(\w+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        group_text = match.group(1).strip()
        for kw, col in column_patterns.items():
            if kw in group_text:
                group_cols.append(col)
                break
        else:
            for kw in table_patterns:
                if kw in group_text:
                    if "部门" in group_text or "department" in group_text:
                        group_cols.append("department")
                    elif "用户" in group_text or "user" in group_text:
                        group_cols.append("user_id")
                    elif "日期" in group_text or "date" in group_text:
                        group_cols.append("date")
                    elif "月" in group_text or "month" in group_text:
                        group_cols.append("MONTH(date)")
                    elif "年" in group_text or "year" in group_text:
                        group_cols.append("YEAR(date)")
                    break
    return group_cols


def extract_ordering(
    text: str,
    column_patterns: Optional[Dict[str, str]] = None,
) -> Optional[Tuple[str, str]]:
    """Extract ORDER BY clause from text.

    Verbatim move of ``nl2sql_legacy._extract_ordering``; ``column_patterns``
    replaces the instance attribute.
    """
    column_patterns = column_patterns or COLUMN_PATTERNS
    order_col = None
    for pattern, column in column_patterns.items():
        if pattern in text:
            order_col = column
            break
    # Use word-boundary matching to avoid false positives (e.g., "orders" contains "order")
    if any(re.search(rf'\b{k}\b', text, re.IGNORECASE) for k in ["排序", "排列", "sort", "order", "sorted"]):
        return (
            order_col or "id",
            "DESC"
            if any(re.search(rf'\b{k}\b', text, re.IGNORECASE) for k in ["降序", "从大到小", "递减", "desc", "descending", "decreasing"])
            else "ASC",
        )
    if any(re.search(rf'\b{k}\b', text, re.IGNORECASE) for k in ["最大", "最高", "最多", "max", "highest", "top"]):
        return (order_col or "amount", "DESC")
    if any(re.search(rf'\b{k}\b', text, re.IGNORECASE) for k in ["最小", "最低", "最少", "min", "lowest"]):
        return (order_col or "amount", "ASC")
    return None
