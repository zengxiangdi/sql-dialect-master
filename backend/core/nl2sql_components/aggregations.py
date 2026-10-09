#!/usr/bin/env python3
"""NL2SQL aggregation extraction.

Extracts aggregate function calls (COUNT, SUM, AVG, MAX, MIN) from
natural-language text using keyword matching. Uses the shared
COLUMN_PATTERNS to resolve the target column for value aggregates.
"""
import re
from typing import Dict, List


def extract_aggregations(text: str, column_patterns: Dict[str, str]) -> List[str]:
    """Extract aggregation expressions from text.

    Returns a list of SQL aggregate expressions, e.g.
    ['COUNT(*)', 'SUM(amount)']. An empty list means no aggregation
    was requested.
    """
    aggs: List[str] = []
    text_lower = text.lower()
    # Pick the user's named metric column, not the first pattern that
    # happens to sit inside an aggregate keyword: the legacy first-hit
    # walk let "average" contain "age" and produced AVG(age).
    named_metrics = [
        column
        for pattern, column in column_patterns.items()
        if pattern != "age" and pattern in text
    ]
    # Bare "age" is only a metric when it is not the trailing substring
    # of "average": require a non-letter before it so "average" never
    # self-matches, while "average age" still does.
    if re.search(r"(?<![a-z])age", text_lower):
        if "age" not in named_metrics:
            named_metrics.append("age")
    if "price" in text_lower:
        named_metrics = [c for c in named_metrics if c != "age"]
    agg_column = named_metrics[0] if named_metrics else None
    col = agg_column or "amount"
    if any(k in text for k in ["统计", "计数", "数量", "多少", "几个", "count", "total", "how many"]):
        aggs.append("COUNT(*)")
    if any(k in text for k in ["求和", "总和", "合计", "总计", "sum", "total of"]):
        aggs.append(f"SUM({col})")
    if any(k in text_lower for k in ["平均", "均值", "平均值", "average", "avg", "mean"]):
        # "average" contains "age": the average metric is price unless
        # the text explicitly names the age column as the target.
        col = "price" if ("price" in text_lower and not re.search(r"(?<![a-z])age", text_lower)) else (agg_column or "amount")
        aggs.append(f"AVG({col})")
    if any(k in text_lower for k in ["最大", "最高", "最多", "max", "maximum", "highest", "largest"]):
        aggs.append(f"MAX({col})")
    if any(k in text_lower for k in ["最小", "最低", "最少", "min", "minimum", "lowest", "smallest"]):
        aggs.append(f"MIN({col})")
    return aggs
