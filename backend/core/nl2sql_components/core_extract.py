#!/usr/bin/env python3
"""Core NL2SQL extraction primitives: operation, table, column, limit, distinct.

These are stateless, dependency-free functions that operate on raw text
and the shared mapping dicts (KEYWORDS, TABLE_PATTERNS, COLUMN_PATTERNS
from ``backend.core.nl2sql_components.mappings``).
"""
import re
from typing import Dict, List, Optional


def detect_operation(text: str, keywords: Dict[str, str]) -> str:
    """Detect SQL operation type from text.

    Scans the keyword mapping for operation keywords present in the text
    and returns the first matching operation (SELECT/INSERT/UPDATE/DELETE).
    Defaults to SELECT.
    """
    for keyword, op in keywords.items():
        if keyword in text and op in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
            return op
    return "SELECT"


def extract_table(text: str, table_patterns: Dict[str, str]) -> str:
    """Extract a single table name from text.

    Prefers the longest matching pattern; ties broken by first position.
    Returns the fallback name "table_name" when no pattern matches.
    """
    tables_found = []
    for pattern, table in table_patterns.items():
        if pattern in text:
            tables_found.append((text.find(pattern), table, len(pattern)))
    if tables_found:
        tables_found.sort(key=lambda item: (-item[2], item[0]))
        return tables_found[0][1]
    return "table_name"


def extract_table_subject(text: str, table_patterns: Dict[str, str]) -> Optional[str]:
    """Extract the subject table (first appearing in text) for D2 relational queries.

    For queries like 'users who have orders', returns 'users' (the subject)
    rather than 'orders' (the relation). Uses first occurrence position.
    """
    candidates = []
    for pattern, table in table_patterns.items():
        if table not in candidates:
            pos = text.find(pattern)
            if pos != -1:
                candidates.append((pos, table))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return None


def named_tables(text: str, table_patterns: Dict[str, str]) -> List[str]:
    """Return the distinct table names the text mentions, in order of first appearance."""
    occurrences = []
    seen = set()
    for pattern, table in table_patterns.items():
        if table in seen:
            continue
        pos = text.find(pattern)
        if pos != -1:
            occurrences.append((pos, table))
            seen.add(table)
    return [t for _, t in sorted(occurrences)]


def extract_columns(text: str, column_patterns: Dict[str, str]) -> List[str]:
    """Extract column names from text.

    Returns a list of distinct column names, or ["*"] when no column
    keyword is present.
    """
    columns = []
    for pattern, column in column_patterns.items():
        if pattern in text and column not in columns:
            columns.append(column)
    return columns if columns else ["*"]


def extract_limit(text: str) -> Optional[int]:
    """Extract LIMIT value from text.

    Supports Chinese and English cardinality phrasings such as
    '前10', 'top 10', 'limit 10', '10条', '10行'.
    """
    patterns = [
        r"前\s*(\d+)", r"top\s*(\d+)", r"limit\s*(\d+)",
        r"first\s*(\d+)", r"(\d+)\s*条", r"(\d+)\s*个",
        r"(\d+)\s*行", r"(\d+)\s*rows?", r"only\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def check_distinct(text: str) -> bool:
    """Check if DISTINCT is requested in the text."""
    return any(k in text for k in ["去重", "唯一", "不重复", "distinct", "unique"])
