"""Compatibility adapters for remaining NL2SQL semantic edge cases."""

import re

from .config import SUPPORTED_DIALECTS
from .nl2sql import NL2SQLGenerator
from .p1_sql_scanner import executable_segments


_original_extract_conditions = NL2SQLGenerator._extract_conditions_enhanced


def _extract_conditions_with_english_inclusive_comparisons(self, text: str, original: str):
    conditions = _original_extract_conditions(self, text, original)

    if re.search(r"\bgreater\s+than\s+or\s+equal\s+to\b", text, re.IGNORECASE):
        conditions = [
            re.sub(r"\s>\s(\d+\.?\d*)$", r" >= \1", condition, count=1)
            for condition in conditions
        ]

    if re.search(r"\bless\s+than\s+or\s+equal\s+to\b", text, re.IGNORECASE):
        conditions = [
            re.sub(r"\s<\s(\d+\.?\d*)$", r" <= \1", condition, count=1)
            for condition in conditions
        ]

    return conditions


NL2SQLGenerator._extract_conditions_enhanced = _extract_conditions_with_english_inclusive_comparisons


_original_apply_dialect_adjustments = NL2SQLGenerator._apply_dialect_adjustments


def _replace_outside(sql: str, pattern: re.Pattern, replacement: str | callable) -> str:
    """Apply a regex only to executable SQL regions."""
    parts = []
    for start, end in executable_segments(sql):
        cursor = 0
        segment = sql[start:end]
        for match in pattern.finditer(segment):
            parts.append(segment[cursor:match.start()])
            parts.append(replacement(match) if callable(replacement) else match.expand(replacement))
            cursor = match.end()
        parts.append(segment[cursor:])
    result = []
    cursor = 0
    for start, end in executable_segments(sql):
        result.append(sql[cursor:start])
        cursor = end
    if cursor < len(sql):
        result.append(sql[cursor:])

    # Rebuild from original segments while preserving all non-executable text.
    output = []
    last = 0
    executable_index = 0
    for start, end in executable_segments(sql):
        output.append(sql[last:start])
        segment = sql[start:end]
        output.append(pattern.sub(replacement, segment) if not callable(replacement) else pattern.sub(replacement, segment))
        last = end
        executable_index += 1
    output.append(sql[last:])
    return "".join(output)


def _apply_dialect_adjustments_safe(self, sql: str, dialect: str):
    """Apply dialect-specific date rewrites without crossing lexical boundaries."""
    dialect = dialect.lower()
    adjusted = sql

    if dialect == "oracle":
        replacements = [
            (re.compile(r"\bDATE_SUB\(CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE), r"TRUNC(SYSDATE) - \1"),
            (re.compile(r"\bDATE_ADD\(CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE), r"TRUNC(SYSDATE) + \1"),
            (re.compile(r"\bADD_MONTHS\(CURRENT_DATE\s*,\s*([+-]?\d+)\s*\)", re.IGNORECASE), r"ADD_MONTHS(TRUNC(SYSDATE), \1)"),
            (re.compile(r"\bCURRENT_TIMESTAMP\b", re.IGNORECASE), "SYSTIMESTAMP"),
            (re.compile(r"\bCURRENT_DATE\b", re.IGNORECASE), "TRUNC(SYSDATE)"),
        ]
    elif dialect == "tsql":
        replacements = [
            (re.compile(r"\bDATE_SUB\(CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE), r"DATEADD(DAY, -\1, CAST(GETDATE() AS DATE))"),
            (re.compile(r"\bDATE_ADD\(CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE), r"DATEADD(DAY, \1, CAST(GETDATE() AS DATE))"),
            (re.compile(r"\bADD_MONTHS\(CURRENT_DATE\s*,\s*([+-]?\d+)\s*\)", re.IGNORECASE), r"DATEADD(MONTH, \1, CAST(GETDATE() AS DATE))"),
            (re.compile(r"\bCURRENT_TIMESTAMP\b", re.IGNORECASE), "SYSDATETIME()"),
            (re.compile(r"\bCURRENT_DATE\b", re.IGNORECASE), "CAST(GETDATE() AS DATE)"),
        ]
    elif dialect in {"postgres", "duckdb"}:
        replacements = [
            (re.compile(r"\bDATE_SUB\(CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE), r"CURRENT_DATE - INTERVAL '\1 days'"),
            (re.compile(r"\bDATE_ADD\(CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE), r"CURRENT_DATE + INTERVAL '\1 days'"),
            (re.compile(r"\bADD_MONTHS\(CURRENT_DATE\s*,\s*([+-]?\d+)\s*\)", re.IGNORECASE), r"CURRENT_DATE + INTERVAL '\1 month'"),
        ]
    elif dialect == "mysql":
        replacements = [
            (re.compile(r"\bADD_MONTHS\(CURRENT_DATE\s*,\s*([+-]?\d+)\s*\)", re.IGNORECASE), lambda m: (
                f"DATE_SUB(CURRENT_DATE, INTERVAL {abs(int(m.group(1)))} MONTH)"
                if int(m.group(1)) < 0
                else f"DATE_ADD(CURRENT_DATE, INTERVAL {m.group(1)} MONTH)"
            )),
        ]
    else:
        return _original_apply_dialect_adjustments(self, sql, dialect)

    for pattern, replacement in replacements:
        adjusted = _replace_outside(adjusted, pattern, replacement)
    return adjusted


NL2SQLGenerator._apply_dialect_adjustments = _apply_dialect_adjustments_safe


_original_template_generate = NL2SQLGenerator._generate_from_template


def _generate_from_template_with_order_semantics(
    self, template, match_groups, analysis, dialect, table_hint, column_hints
):
    """Generate a template query and normalize dialect-specific top-N semantics."""
    result = _original_template_generate(
        self, template, match_groups, analysis, dialect, table_hint, column_hints
    )
    if not result.success or template.name != "top_n_query" or not result.sql:
        return result

    request_text = str((match_groups or {}).get("match", "")).lower()
    ascending_requested = bool(re.search(r"\b(bottom|lowest|smallest)\b|最低|最少", request_text))
    if ascending_requested:
        result.sql = _replace_outside(
            result.sql,
            re.compile(r"(ORDER BY\s+[^\n]+?)\s+DESC\b", re.IGNORECASE),
            r"\1 ASC",
        )
        result.explanation = re.sub(r"查询前(\d+)条记录", r"查询最低/最少\1条记录", result.explanation)

    if dialect == "oracle":
        limit_match = re.search(r"\bLIMIT\s+(\d+)\s*$", result.sql, re.IGNORECASE)
        if limit_match:
            n = limit_match.group(1)
            result.sql = _replace_outside(
                result.sql,
                re.compile(r"\s+LIMIT\s+\d+\s*$", re.IGNORECASE),
                "",
            ).rstrip()
            result.sql += f"\nFETCH FIRST {n} ROWS ONLY"
    elif dialect == "tsql":
        limit_match = re.search(r"\bLIMIT\s+(\d+)\s*$", result.sql, re.IGNORECASE)
        if limit_match:
            n = limit_match.group(1)
            result.sql = _replace_outside(
                result.sql,
                re.compile(r"\s+LIMIT\s+\d+\s*$", re.IGNORECASE),
                "",
            )
            result.sql = _replace_outside(
                result.sql,
                re.compile(r"\bSELECT\s+", re.IGNORECASE),
                f"SELECT TOP {n} ",
            )
    return result


NL2SQLGenerator._generate_from_template = _generate_from_template_with_order_semantics


_original_generate = NL2SQLGenerator.generate
_SAFE_TABLE_HINT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*")


def _generate_normalized(self, text: str, dialect: str = None, table_hint: str = None, column_hints=None):
    """Normalize direct-call inputs so core and API callers share dialect semantics."""
    normalized_dialect = (dialect or self.default_dialect).strip().lower()
    if normalized_dialect not in SUPPORTED_DIALECTS:
        raise ValueError(f"Unsupported dialect: {dialect}. Supported: {', '.join(SUPPORTED_DIALECTS)}")
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized_table_hint = table_hint.strip() if isinstance(table_hint, str) else table_hint
    if normalized_table_hint and not _SAFE_TABLE_HINT.fullmatch(normalized_table_hint):
        raise ValueError("table_hint must be a simple SQL identifier or dotted identifier")
    return _original_generate(self, text, normalized_dialect, normalized_table_hint, column_hints)


NL2SQLGenerator.generate = _generate_normalized
