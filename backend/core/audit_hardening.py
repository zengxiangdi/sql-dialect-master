"""Consolidated semantic and security hardening layer for SQL Dialect Master.

The legacy implementation has several regex-based post-processing hooks. This
module adds one deterministic boundary around them: source inspection is quote
and comment aware, security checks prefer ASTs, and transformations that cannot
be proven equivalent are left unchanged with an explicit note.
"""

from typing import Callable, Optional
import re

import sqlglot
from sqlglot import exp

from .config import DANGEROUS_SQL_PATTERNS, WARNING_SQL_PATTERNS, settings
from .nl2sql import NL2SQLGenerator
from .post_processor import PostProcessor
from .rules import TransformRule
from .transpiler import SQLTranspiler


_ORIGINAL_PROCESS = PostProcessor.process


def _scan_segments(sql: str):
    """Yield (kind, text) segments: executable, quoted, or comment."""
    i = 0
    start = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', '`') or ch == '[':
            if start < i:
                yield "code", sql[start:i]
            quote = ']' if ch == '[' else ch
            qstart = i
            i += 1
            while i < n:
                if quote == "'" and sql[i] == '\\' and i + 1 < n:
                    i += 2
                    continue
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            yield "quoted", sql[qstart:i]
            start = i
            continue
        if ch == '-' and i + 1 < n and sql[i + 1] == '-':
            if start < i:
                yield "code", sql[start:i]
            j = i + 2
            while j < n and sql[j] not in '\r\n':
                j += 1
            yield "comment", sql[i:j]
            i = j
            start = i
            continue
        if ch == '/' and i + 1 < n and sql[i + 1] == '*':
            if start < i:
                yield "code", sql[start:i]
            j = i + 2
            while j + 1 < n and not (sql[j] == '*' and sql[j + 1] == '/'):
                j += 1
            j = min(n, j + 2)
            yield "comment", sql[i:j]
            i = j
            start = i
            continue
        i += 1
    if start < n:
        yield "code", sql[start:]


def _mask_non_executable(sql: str) -> str:
    """Replace strings, quoted identifiers and comments with spaces."""
    return ''.join(
        text if kind == "code" else ''.join('\n' if c in '\r\n' else ' ' for c in text)
        for kind, text in _scan_segments(sql)
    )


def _replace_outside(sql: str, pattern: re.Pattern, replacement: str | Callable[[re.Match], str]):
    """Regex-rewrite executable SQL only."""
    parts = []
    count = 0
    for kind, text in _scan_segments(sql):
        if kind == "code":
            text, changed = pattern.subn(replacement, text)
            count += changed
        parts.append(text)
    return ''.join(parts), count


def _top_level_keyword(text: str, keyword: str) -> int:
    """Find a top-level keyword without matching nested function arguments or literals."""
    wanted = keyword.upper()
    depth = 0
    quote: Optional[str] = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote is not None:
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
            elif quote == "'" and ch == '\\' and i + 1 < len(text):
                i += 2
                continue
            i += 1
            continue
        if ch in ("'", '"', '`'):
            quote = ch
            i += 1
            continue
        if ch == '(':
            depth += 1
            i += 1
            continue
        if ch == ')':
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and text[i:i + len(wanted)].upper() == wanted:
            before = text[i - 1] if i else ' '
            after = text[i + len(wanted)] if i + len(wanted) < len(text) else ' '
            if not (before.isalnum() or before == '_') and not (after.isalnum() or after == '_'):
                return i
        i += 1
    return -1


def _dml_without_where(sql: str):
    """Return UPDATE/DELETE statements that have no WHERE clause."""
    try:
        trees = sqlglot.parse(sql)
    except Exception:
        return []
    result = []
    for tree in trees:
        for node in tree.walk():
            if isinstance(node, exp.Update) and node.args.get("where") is None:
                result.append("UPDATE")
            elif isinstance(node, exp.Delete) and node.args.get("where") is None:
                result.append("DELETE")
    return result


def _validate_security(self, sql: str):
    result = {"blocked": False, "reason": None, "warnings": []}
    masked = _mask_non_executable(sql)
    try:
        statements = sqlglot.parse(sql)
        if len(statements) > 1:
            message = "Multiple SQL statements detected"
            if settings.security_block_dangerous:
                result["blocked"] = True
                result["reason"] = message
                return result
            result["warnings"].append(f"🔒 Security: {message}")
    except Exception:
        pass
    for pattern, message in DANGEROUS_SQL_PATTERNS:
        if pattern.search(masked):
            if settings.security_block_dangerous:
                result["blocked"] = True
                result["reason"] = message
                return result
            result["warnings"].append(f"🔒 Security: {message}")
    for op in _dml_without_where(sql):
        result["warnings"].append(f"⚠️ {op} without WHERE clause - may affect all rows")
    for pattern, message in WARNING_SQL_PATTERNS:
        if pattern.search(masked):
            result["warnings"].append(f"⚠️ {message}")
    return result


SQLTranspiler._validate_security = _validate_security


def _generate_warnings(self, sql: str, source: str, target: str):
    masked = _mask_non_executable(sql).upper()
    warnings = []
    if "DROP TABLE" in masked or "TRUNCATE" in masked:
        warnings.append("⚠️ Dangerous operation detected: DROP/TRUNCATE")
    for op in _dml_without_where(sql):
        warnings.append(f"⚠️ {op} without WHERE clause - will affect all rows")
    if "SELECT *" in masked:
        warnings.append("💡 Consider specifying columns instead of SELECT *")
    if "CROSS JOIN" in masked:
        warnings.append("💡 CROSS JOIN can produce large result sets")
    if len(re.findall(r"\bJOIN\b", masked)) > 5:
        warnings.append("💡 Query has many JOINs - consider query optimization")
    if source == "hive" and target in {"mysql", "postgres", "oracle"}:
        if "DISTRIBUTE BY" in masked or "CLUSTER BY" in masked:
            warnings.append("⚠️ DISTRIBUTE BY/CLUSTER BY are Hive-specific hints, removed in target")
        if "SORT BY" in masked:
            warnings.append("⚠️ SORT BY is Hive-specific, converted to ORDER BY")
    if source in {"hive", "spark"} and target in {"mysql", "postgres"}:
        if "COLLECT_LIST" in masked or "COLLECT_SET" in masked:
            warnings.append("💡 Array aggregation converted - verify result format")
    return warnings


SQLTranspiler._generate_warnings = _generate_warnings


def _simple_rownum_transform(sql: str):
    """Convert only a simple top-level ROWNUM <= N predicate."""
    masked = _mask_non_executable(sql)
    upper = masked.upper()
    if "ROWNUM" not in upper:
        return sql, None
    if len(re.findall(r"\bSELECT\b", upper)) != 1:
        return sql, "Skipped automatic ROWNUM conversion because query shape is not provably LIMIT-equivalent"
    if any(token in upper for token in (" OR ", " UNION ", " INTERSECT ", " EXCEPT ", " ORDER BY ", " GROUP BY ", " HAVING ", " DISTINCT ")):
        return sql, "Skipped automatic ROWNUM conversion because query shape is not provably LIMIT-equivalent"
    match = re.search(r"\bROWNUM\s*<=\s*(\d+)\b", masked, re.IGNORECASE)
    if not match:
        return sql, "Skipped automatic ROWNUM conversion because query shape is not provably LIMIT-equivalent"
    n = match.group(1)
    patterns = [
        (re.compile(r"\s+AND\s+ROWNUM\s*<=\s*\d+\b", re.IGNORECASE), ""),
        (re.compile(r"\bWHERE\s+ROWNUM\s*<=\s*\d+\s+AND\s+", re.IGNORECASE), "WHERE "),
        (re.compile(r"\bWHERE\s+ROWNUM\s*<=\s*\d+\b", re.IGNORECASE), ""),
    ]
    for pattern, replacement in patterns:
        result, count = _replace_outside(sql, pattern, replacement)
        if count:
            return result.rstrip(';').rstrip() + f" LIMIT {n}", f"Converted simple ROWNUM <= {n} to LIMIT {n}"
    return sql, "Skipped automatic ROWNUM conversion because predicate shape was not safely removable"


def _rownum_conversion(self, sql: str):
    return _simple_rownum_transform(sql)


PostProcessor._convert_rownum_to_limit = _rownum_conversion


def _group_concat(args: str, original: str) -> str:
    sep_pos = _top_level_keyword(args, "SEPARATOR")
    before_sep = args
    separator = "','"
    if sep_pos >= 0:
        before_sep = args[:sep_pos].rstrip()
        separator = args[sep_pos + len("SEPARATOR"):].strip() or separator
    order_pos = _top_level_keyword(before_sep, "ORDER BY")
    expression = before_sep
    order_by = None
    if order_pos >= 0:
        expression = before_sep[:order_pos].rstrip()
        order_by = before_sep[order_pos + len("ORDER BY"):].strip()
    distinct = expression[:9].upper() == "DISTINCT "
    if distinct:
        expression = expression[9:].strip()
    if not expression:
        return original
    distinct_sql = "DISTINCT " if distinct else ""
    result = f"STRING_AGG({distinct_sql}({expression})::TEXT, {separator}"
    if order_by:
        result += f" ORDER BY {order_by}"
    return result + ")"


def _process(self, sql: str, source: str, target: str):
    working = sql
    notes = []
    source_l = source.lower()
    target_l = target.lower()

    # The legacy processor can incorrectly turn complex ROWNUM predicates into
    # LIMIT. Only allow its ROWNUM path after a conservative equivalence check.
    if source_l == "oracle" and target_l in {"mysql", "postgres", "hive", "spark"} and "ROWNUM" in _mask_non_executable(working).upper():
        converted, note = _simple_rownum_transform(working)
        if note and converted != working:
            working = converted
            notes.append(note)
        elif note:
            working, _ = _replace_outside(working, re.compile(r"\bROWNUM\b", re.IGNORECASE), "__SDM_ROWNUM_SENTINEL__")
            notes.append(note)
            result, legacy_notes = _ORIGINAL_PROCESS(self, working, source, target)
            result = result.replace("__SDM_ROWNUM_SENTINEL__", "ROWNUM")
            return result, notes + legacy_notes

    # Use a sentinel so the legacy GROUP_CONCAT rule cannot consume nested
    # arguments before the robust function-call scanner handles them.
    if source_l == "mysql" and target_l == "postgres" and "GROUP_CONCAT" in _mask_non_executable(working).upper():
        working, count = _replace_outside(working, re.compile(r"\bGROUP_CONCAT\s*\(", re.IGNORECASE), "__SDM_GROUP_CONCAT__(")
        if count:
            working = self._replace_function_calls(working, "__SDM_GROUP_CONCAT__", _group_concat)
            result, legacy_notes = _ORIGINAL_PROCESS(self, working, source, target)
            return result, notes + legacy_notes

    result, legacy_notes = _ORIGINAL_PROCESS(self, working, source, target)
    return result, notes + legacy_notes


PostProcessor.process = _process


def _apply_rule(self, sql: str):
    if not self.enabled:
        return sql, False
    pattern = getattr(self, "_compiled_pattern", None) or re.compile(self.pattern, re.IGNORECASE)
    self._compiled_pattern = pattern
    result, count = _replace_outside(sql, pattern, self.replacement)
    return result, count > 0


TransformRule.apply = _apply_rule


def _apply_dialect_adjustments(self, sql: str, dialect: str):
    if dialect == "oracle":
        result, _ = _replace_outside(sql, re.compile(r"CURRENT_DATE", re.IGNORECASE), "TRUNC(SYSDATE)")
        result, _ = _replace_outside(result, re.compile(r"DATE_SUB\(TRUNC\(SYSDATE\),\s*(\d+)\)", re.IGNORECASE), r"TRUNC(SYSDATE) - \1")
        return result
    if dialect == "tsql":
        result, _ = _replace_outside(sql, re.compile(r"CURRENT_DATE", re.IGNORECASE), "CAST(GETDATE() AS DATE)")
        result, _ = _replace_outside(result, re.compile(r"DATE_SUB\(CAST\(GETDATE\(\) AS DATE\),\s*(\d+)\)", re.IGNORECASE), r"DATEADD(DAY, -\1, CAST(GETDATE() AS DATE))")
        return result
    if dialect == "postgres":
        result, _ = _replace_outside(sql, re.compile(r"DATE_SUB\(CURRENT_DATE,\s*(\d+)\)", re.IGNORECASE), r"CURRENT_DATE - INTERVAL '\1 days'")
        return result
    return sql


NL2SQLGenerator._apply_dialect_adjustments = _apply_dialect_adjustments
