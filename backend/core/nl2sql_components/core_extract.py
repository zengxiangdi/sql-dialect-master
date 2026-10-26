#!/usr/bin/env python3
"""Core NL2SQL extraction primitives: operation, table, column, limit, distinct.

These are stateless, dependency-free functions that operate on raw text
and the shared mapping dicts (KEYWORDS, TABLE_PATTERNS, COLUMN_PATTERNS
from ``backend.core.nl2sql_components.mappings``).
"""
import re
from typing import Dict, List, Optional

from ..p1_sql_scanner import mask_non_executable


# Generated SQL is intended to be reviewed and parameterized by a caller.
# Refuse unbounded/absurd row counts before integer conversion (which can
# raise ValueError for thousands of digits on modern Python versions).
MAX_NL2SQL_LIMIT = 1_000_000


def _pattern_match(text: str, pattern: str) -> Optional[re.Match]:
    """Match an NL2SQL mapping as a token when it is an English identifier.

    Substring matching turns ``update`` into the ``date`` column and can
    similarly match ``order`` inside unrelated words.  Chinese phrases do
    not have whitespace boundaries, so those retain substring semantics.
    """
    expression = re.escape(pattern)
    if not re.search(r"[\u4e00-\u9fff]", pattern):
        expression = rf"(?<![\w$]){expression}(?![\w$])"
    return re.search(expression, text, re.IGNORECASE)


def detect_operation(text: str, keywords: Dict[str, str]) -> str:
    """Detect SQL operation type from text.

    Scans the keyword mapping for operation keywords present in the text
    and returns the first matching operation (SELECT/INSERT/UPDATE/DELETE).
    Defaults to SELECT.
    """
    intent_text = mask_non_executable(text)
    # Deletion-state phrases describe a SELECT predicate. Mask only the
    # phrase so an independent leading "删除" in e.g. "删除已删除用户"
    # remains a genuine DELETE intent.
    intent_text = re.sub(
        r"(?:已删除|未删除|没有删除|不是删除|非删除|already\s+deleted|not\s+deleted)",
        lambda match: " " * len(match.group(0)),
        intent_text,
        flags=re.IGNORECASE,
    )
    for keyword, op in keywords.items():
        if _pattern_match(intent_text, keyword) and op in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
            return op
    return "SELECT"


def extract_table(text: str, table_patterns: Dict[str, str]) -> str:
    """Extract a single table name from text.

    Prefers the longest matching pattern; ties broken by first position.
    Returns the fallback name "table_name" when no pattern matches.
    """
    tables_found = []
    for pattern, table in table_patterns.items():
        match = _pattern_match(text, pattern)
        if match:
            tables_found.append((match.start(), table, len(pattern)))
    if tables_found:
        tables_found.sort(key=lambda item: (-item[2], item[0]))
        return tables_found[0][1]
    return "table_name"


def extract_table_subject(
    text: str, table_patterns: Dict[str, str], relational_context: str = ""
) -> Optional[str]:
    """Extract the subject table (first appearing in text) for D2 relational queries.

    For queries like 'users who have orders', returns 'users' (the subject)
    rather than 'orders' (the relation). Uses first occurrence position.

    ``relational_context`` names the relation table when the caller already
    resolved one from the relational keyword set (e.g. the CN 有订单
    connective maps 订单 → orders).  That table must not win the subject
    slot even when it is the earliest-matching pattern, so every candidate
    table equal to it is excluded before the first-occurrence sort.
    """
    candidates = []
    for pattern, table in table_patterns.items():
        if relational_context and table == relational_context:
            continue
        match = _pattern_match(text, pattern)
        pos = match.start() if match else -1
        if pos != -1:
            if table in [t for _, t in candidates]:
                continue
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
        match = _pattern_match(text, pattern)
        pos = match.start() if match else -1
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
    text = mask_non_executable(text)
    for pattern, column in column_patterns.items():
        if _pattern_match(text, pattern) and column not in columns:
            columns.append(column)
    return columns if columns else ["*"]


def extract_limit(text: str) -> Optional[int]:
    """Extract LIMIT value from text.

    Supports Chinese and English cardinality phrasings such as
    '前10', 'top 10', 'limit 10', '10条', '10行'.
    """
    patterns = [
        r"前\s*(-?\d+)", r"top\s*(-?\d+)", r"limit\s*(-?\d+)",
        r"first\s*(-?\d+)", r"(-?\d+)\s*条", r"(-?\d+)\s*个",
        r"(-?\d+)\s*行", r"(-?\d+)\s*rows?", r"only\s*(-?\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw_value = match.group(1)
            # Keep the conversion bounded and deterministic.  Raising here is
            # handled by the generator as a client-facing failed generation;
            # silently dropping an invalid limit could produce an unbounded
            # query.
            if raw_value.startswith("-"):
                raise ValueError("LIMIT cannot be negative")
            if len(raw_value) > 64:
                raise ValueError("LIMIT number representation exceeds the maximum supported length")
            normalized_value = raw_value.lstrip("0") or "0"
            if len(normalized_value) > len(str(MAX_NL2SQL_LIMIT)):
                raise ValueError(
                    f"LIMIT exceeds maximum supported value of {MAX_NL2SQL_LIMIT}"
                )
            value = int(normalized_value)
            if value > MAX_NL2SQL_LIMIT:
                raise ValueError(
                    f"LIMIT exceeds maximum supported value of {MAX_NL2SQL_LIMIT}"
                )
            return value
    return None


def check_distinct(text: str) -> bool:
    """Check if DISTINCT is requested in the text."""
    return any(k in text for k in ["去重", "唯一", "不重复", "distinct", "unique"])
