#!/usr/bin/env python3
"""NL2SQL aggregation extraction.

Extracts aggregate function calls (COUNT, SUM, AVG, MAX, MIN) from
natural-language text using keyword matching. Uses the shared
COLUMN_PATTERNS to resolve the target column for value aggregates.
"""
from typing import Dict, List


def extract_aggregations(text: str, column_patterns: Dict[str, str]) -> List[str]:
    """Extract aggregation expressions from text.

    Returns a list of SQL aggregate expressions, e.g.
    ['COUNT(*)', 'SUM(amount)']. An empty list means no aggregation
    was requested.
    """
    aggs: List[str] = []
    agg_column = None
    for pattern, column in column_patterns.items():
        if pattern in text:
            agg_column = column
            break
    col = agg_column or "amount"
    if any(k in text for k in ["统计", "计数", "数量", "多少", "几个", "count", "total", "how many"]):
        aggs.append("COUNT(*)")
    if any(k in text for k in ["求和", "总和", "合计", "总计", "sum", "total of"]):
        aggs.append(f"SUM({col})")
    if any(k in text for k in ["平均", "均值", "平均值", "average", "avg", "mean"]):
        aggs.append(f"AVG({col})")
    if any(k in text for k in ["最大", "最高", "最多", "max", "maximum", "highest", "largest"]):
        aggs.append(f"MAX({col})")
    if any(k in text for k in ["最小", "最低", "最少", "min", "minimum", "lowest", "smallest"]):
        aggs.append(f"MIN({col})")
    return aggs
