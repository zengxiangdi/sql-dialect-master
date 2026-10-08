#!/usr/bin/env python3
"""P8 NL2SQL pipeline: dialect rewriter (moved UNCHANGED from nl2sql_legacy).

Regex-based, executable-region-aware dialect adjustment.  In P8 this module
is a verbatim move; AST-based rewriting is deferred to a future phase.
"""
import re
from typing import Callable

from ..p1_sql_scanner import executable_segments

# Pattern types shared by the per-dialect replacement tables.
_re_p = re.Pattern
_re_s = str | Callable[[re.Match], str]


def apply_dialect_adjustments(sql: str, dialect: str) -> str:
    """Apply dialect-specific syntax adjustments.

    Uses executable-region-aware replacement so literals, comments, and
    quoted identifiers are never modified.
    """
    dialect = dialect.lower()

    if dialect == "hive":
        return sql

    replacements: list[tuple[_re_p, _re_s]] = []

    if dialect == "oracle":
        # Handle DATE_SUB/DATE_ADD/ADD_MONTHS with CURRENT_DATE first,
        # then handle the already-converted forms (TRUNC(SYSDATE)).
        replacements = [
            (
                re.compile(
                    r"\bDATE_SUB\(\s*(?:TRUNC\(SYSDATE\)|CURRENT_DATE)\s*,\s*(\d+)\s*\)",
                    re.IGNORECASE,
                ),
                r"TRUNC(SYSDATE) - \1",
            ),
            (
                re.compile(
                    r"\bDATE_ADD\(\s*(?:TRUNC\(SYSDATE\)|CURRENT_DATE)\s*,\s*(\d+)\s*\)",
                    re.IGNORECASE,
                ),
                r"TRUNC(SYSDATE) + \1",
            ),
            (
                re.compile(
                    r"\bADD_MONTHS\(\s*(?:TRUNC\(SYSDATE\)|CURRENT_DATE)\s*,\s*([+-]?\d+)\s*\)",
                    re.IGNORECASE,
                ),
                r"ADD_MONTHS(TRUNC(SYSDATE), \1)",
            ),
            (re.compile(r"\bCURRENT_TIMESTAMP\b", re.IGNORECASE), "SYSTIMESTAMP"),
            (re.compile(r"\bCURRENT_DATE\b", re.IGNORECASE), "TRUNC(SYSDATE)"),
        ]
    elif dialect == "tsql":
        replacements = [
            (
                re.compile(
                    r"\bDATE_SUB\(\s*(?:CAST\(GETDATE\(\)\s+AS\s+DATE\)|CURRENT_DATE)\s*,\s*(\d+)\s*\)",
                    re.IGNORECASE,
                ),
                r"DATEADD(DAY, -\1, CAST(GETDATE() AS DATE))",
            ),
            (
                re.compile(
                    r"\bDATE_ADD\(\s*(?:CAST\(GETDATE\(\)\s+AS\s+DATE\)|CURRENT_DATE)\s*,\s*(\d+)\s*\)",
                    re.IGNORECASE,
                ),
                r"DATEADD(DAY, \1, CAST(GETDATE() AS DATE))",
            ),
            (
                re.compile(
                    r"\bADD_MONTHS\(\s*(?:CAST\(GETDATE\(\)\s+AS\s+DATE\)|CURRENT_DATE)\s*,\s*([+-]?\d+)\s*\)",
                    re.IGNORECASE,
                ),
                r"DATEADD(MONTH, \1, CAST(GETDATE() AS DATE))",
            ),
            (re.compile(r"\bCURRENT_TIMESTAMP\b", re.IGNORECASE), "SYSDATETIME()"),
            (re.compile(r"\bCURRENT_DATE\b", re.IGNORECASE), "CAST(GETDATE() AS DATE)"),
        ]
    elif dialect == "mysql":
        replacements = [
            (
                re.compile(r"\bDATE_SUB\(\s*CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE),
                r"DATE_SUB(CURRENT_DATE, INTERVAL \1 DAY)",
            ),
            (
                re.compile(r"\bDATE_ADD\(\s*CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE),
                r"DATE_ADD(CURRENT_DATE, INTERVAL \1 DAY)",
            ),
            (
                re.compile(
                    r"\bADD_MONTHS\(\s*CURRENT_DATE\s*,\s*([+-]?\d+)\s*\)",
                    re.IGNORECASE,
                ),
                lambda match: (
                    f"DATE_SUB(CURRENT_DATE, INTERVAL {abs(int(match.group(1)))} MONTH)"
                    if int(match.group(1)) < 0
                    else f"DATE_ADD(CURRENT_DATE, INTERVAL {match.group(1)} MONTH)"
                ),
            ),
        ]
    elif dialect in ("postgres", "duckdb"):
        replacements = [
            (
                re.compile(r"\bDATE_SUB\(\s*CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE),
                r"CURRENT_DATE - INTERVAL '\1 days'",
            ),
            (
                re.compile(r"\bDATE_ADD\(\s*CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE),
                r"CURRENT_DATE + INTERVAL '\1 days'",
            ),
            (
                re.compile(
                    r"\bADD_MONTHS\(\s*CURRENT_DATE\s*,\s*([+-]?\d+)\s*\)",
                    re.IGNORECASE,
                ),
                r"CURRENT_DATE + INTERVAL '\1 month'",
            ),
        ]
    else:
        return sql

    for pattern, replacement in replacements:
        parts = []
        cursor = 0
        for start, end in executable_segments(sql):
            parts.append(sql[cursor:start])
            segment = sql[start:end]
            segment = pattern.sub(replacement, segment)
            parts.append(segment)
            cursor = end
        parts.append(sql[cursor:])
        sql = "".join(parts)

    return sql
