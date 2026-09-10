"""Consolidated semantic and security hardening layer for SQL Dialect Master."""

from typing import Callable
import logging
import re

import sqlglot
from sqlglot import exp

from .config import DANGEROUS_SQL_PATTERNS, WARNING_SQL_PATTERNS, settings
from .nl2sql import NL2SQLGenerator
from .post_processor import PostProcessor
from .rules import TransformRule
from .transpiler import SQLTranspiler
from .p1_sql_scanner import mask_non_executable

logger = logging.getLogger(__name__)
_ORIGINAL_PROCESS = PostProcessor.process
_DANGEROUS_OPERATION_PATTERN = re.compile(r"\b(DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b", re.IGNORECASE)


def _scan_segments(sql: str):
    """Split SQL into executable, quoted-literal, and comment segments."""
    i = 0
    start = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "$":
            match = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if match:
                delimiter = match.group(0)
                if start < i:
                    yield "code", sql[start:i]
                qstart = i
                end = sql.find(delimiter, i + len(delimiter))
                i = n if end < 0 else end + len(delimiter)
                yield "quoted", sql[qstart:i]
                start = i
                continue
        if ch in "qQ" and i + 2 < n and sql[i + 1] == "'":
            opener = sql[i + 2]
            closer = {"[": "]", "{": "}", "(": ")", "<": ">"}.get(opener, opener)
            end = sql.find(f"{closer}'", i + 3)
            if end >= 0:
                if start < i:
                    yield "code", sql[start:i]
                end += 2
                yield "quoted", sql[i:end]
                i = end
                start = i
                continue
        if ch in ("'", '"', '`') or ch == '[':
            if start < i:
                yield "code", sql[start:i]
            quote = ']' if ch == '[' else ch
            qstart = i
            i += 1
            while i < n:
                if quote == "'" and sql[i] == "\\" and i + 1 < n:
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
            while j < n and sql[j] not in "\r\n":
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
    return mask_non_executable(sql)


def _replace_outside(sql: str, pattern: re.Pattern, replacement: str | Callable[[re.Match], str]):
    parts = []
    count = 0
    for kind, text in _scan_segments(sql):
        if kind == "code":
            text, changed = pattern.subn(replacement, text)
            count += changed
        parts.append(text)
    return ''.join(parts), count


def _top_level_keyword(text: str, keyword: str) -> int:
    wanted = keyword.upper()
    depth = 0
    quote = None
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


def _dml_without_where(sql: str, parsed_statements=None):
    """Return DML operations without WHERE, reusing parsed statements when provided."""
    if parsed_statements is None:
        try:
            parsed_statements = sqlglot.parse(sql)
        except Exception as exc:
            logger.debug("Security AST parse fallback: %s", exc)
            return []
    result = []
    for tree in parsed_statements:
        if tree is None:
            continue
        for node in tree.walk():
            if isinstance(node, exp.Update) and node.args.get("where") is None:
                result.append("UPDATE")
            elif isinstance(node, exp.Delete) and node.args.get("where") is None:
                result.append("DELETE")
    return result


def _validate_security(self, sql: str):
    masked = _mask_non_executable(sql)
    result = {
        "blocked": False,
        "reason": None,
        "warnings": [],
        "executable_sql": masked,
        "multiple_statements": False,
    }
    dangerous_operation = _DANGEROUS_OPERATION_PATTERN.search(masked)
    if dangerous_operation:
        message = f"Dangerous SQL operation detected: {dangerous_operation.group(1).upper()}"
        if settings.security_block_dangerous:
            result["blocked"] = True
            result["reason"] = message
            return result
        result["warnings"].append(f"🔒 Security: {message}")

    has_executable_separator = ";" in sql and ";" in masked
    parsed_statements = None
    if has_executable_separator:
        try:
            parsed_statements = sqlglot.parse(sql)
            result["multiple_statements"] = len(parsed_statements) > 1
            if result["multiple_statements"]:
                message = "Multiple SQL statements detected"
                if settings.security_block_dangerous:
                    result["blocked"] = True
                    result["reason"] = message
                    return result
                result["warnings"].append(f"🔒 Security: {message}")
        except Exception as exc:
            logger.debug("Stacked-statement AST parse unavailable; using masked regex fallback: %s", exc)

    masked_upper = masked.upper()
    needs_dml_ast = bool(re.search(r"\b(?:UPDATE|DELETE)\b", masked_upper))
    if needs_dml_ast and parsed_statements is None:
        try:
            parsed_statements = sqlglot.parse(sql)
        except Exception as exc:
            logger.debug("DML security AST parse unavailable: %s", exc)
            parsed_statements = None

    for pattern, message in DANGEROUS_SQL_PATTERNS:
        if pattern.search(masked):
            if settings.security_block_dangerous:
                result["blocked"] = True
                result["reason"] = message
                return result
            result["warnings"].append(f"🔒 Security: {message}")

    if parsed_statements is not None and needs_dml_ast:
        dml_without_where = set(_dml_without_where(sql, parsed_statements))
        for op in sorted(dml_without_where):
            result["warnings"].append(f"⚠️ {op} without WHERE clause - may affect all rows")

    for pattern, message in WARNING_SQL_PATTERNS:
        if message in {
            "DELETE without WHERE clause - will affect all rows",
            "UPDATE without WHERE clause - will affect all rows",
        }:
            continue
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
    return warnings

SQLTranspiler._generate_warnings = _generate_warnings


def _simple_rownum_transform(sql: str):
    masked = _mask_non_executable(sql)
    upper = masked.upper()
    if "ROWNUM" not in upper:
        return sql, None
    if len(re.findall(r"\bSELECT\b", upper)) != 1 or any(token in upper for token in (" OR ", " UNION ", " INTERSECT ", " EXCEPT ", " ORDER BY ", " GROUP BY ", " HAVING ", " DISTINCT ")):
        return sql, "Skipped automatic ROWNUM conversion because query shape is not provably LIMIT-equivalent"
    match = re.search(r"\bROWNUM\s*<=\s*(\d+)\b", masked, re.IGNORECASE)
    if not match:
        return sql, "Skipped automatic ROWNUM conversion because query shape is not provably LIMIT-equivalent"
    n = match.group(1)
    for pattern, replacement in [
        (re.compile(r"\s+AND\s+ROWNUM\s*<=\s*\d+\b", re.IGNORECASE), ""),
        (re.compile(r"\bWHERE\s+ROWNUM\s*<=\s*\d+\s+AND\s+", re.IGNORECASE), "WHERE "),
        (re.compile(r"\bWHERE\s+ROWNUM\s*<=\s*\d+\b", re.IGNORECASE), ""),
    ]:
        result, count = _replace_outside(sql, pattern, replacement)
        if count:
            return result.rstrip(';').rstrip() + f" LIMIT {n}", f"Converted simple ROWNUM <= {n} to LIMIT {n}"
    return sql, "Skipped automatic ROWNUM conversion because predicate shape was not safely removable"


def _convert_rownum_to_limit(self, sql: str):
    result, note = _simple_rownum_transform(sql)
    return result, ([note] if note else [])

PostProcessor._convert_rownum_to_limit = _convert_rownum_to_limit


def _group_concat(args: str, original: str) -> str:
    sep_pos = _top_level_keyword(args, "SEPARATOR")
    before_sep = args
    separator = "','"
    if sep_pos >= 0:
        before_sep = args[:sep_pos].rstrip()
        separator = args[sep_pos + 9:].strip() or separator
    order_pos = _top_level_keyword(before_sep, "ORDER BY")
    expression = before_sep
    order_by = None
    if order_pos >= 0:
        expression = before_sep[:order_pos].rstrip()
        order_by = before_sep[order_pos + 8:].strip()
    distinct = expression[:9].upper() == "DISTINCT "
    if distinct:
        expression = expression[9:].strip()
    if not expression:
        return original
    needs_parentheses = distinct or not re.fullmatch(r"[A-Za-z_][\w$.]*", expression)
    rendered_expression = f"({expression})" if needs_parentheses else expression
    result = f"STRING_AGG({'DISTINCT ' if distinct else ''}{rendered_expression}::TEXT, {separator}"
    if order_by:
        result += f" ORDER BY {order_by}"
    return result + ")"


def _process(self, sql: str, source: str, target: str):
    working = sql
    notes = []
    source_l = source.lower()
    target_l = target.lower()
    if source_l == "oracle" and target_l in {"mysql", "postgres", "hive", "spark"} and "ROWNUM" in _mask_non_executable(working).upper():
        converted, note = _simple_rownum_transform(working)
        if note and converted != working:
            working = converted
            notes.append(note)
            result, legacy_notes = _ORIGINAL_PROCESS(self, working, source, target)
            return result, notes + legacy_notes
        elif note:
            working, _ = _replace_outside(working, re.compile(r"\bROWNUM\b", re.IGNORECASE), "__SDM_ROWNUM_SENTINEL__")
            notes.append(note)
            result, legacy_notes = _ORIGINAL_PROCESS(self, working, source, target)
            return result.replace("__SDM_ROWNUM_SENTINEL__", "ROWNUM"), notes + legacy_notes
    if source_l == "mysql" and target_l == "postgres" and "GROUP_CONCAT" in _mask_non_executable(working).upper():
        working, count = _replace_outside(working, re.compile(r"\bGROUP_CONCAT\s*\(", re.IGNORECASE), "__SDM_GROUP_CONCAT__(")
        if count:
            working = self._replace_function_calls(working, "__SDM_GROUP_CONCAT__", _group_concat)
            return _ORIGINAL_PROCESS(self, working, source, target)
    return _ORIGINAL_PROCESS(self, working, source, target)

PostProcessor.process = _process


def _apply_rule(self, sql: str):
    if not self.enabled:
        return sql, False
    pattern = getattr(self, '_compiled_pattern', None) or re.compile(self.pattern, re.IGNORECASE)
    self._compiled_pattern = pattern
    result, count = _replace_outside(sql, pattern, self.replacement)
    return result, count > 0

TransformRule.apply = _apply_rule


def _apply_dialect_adjustments(self, sql: str, dialect: str):
    if dialect == "oracle":
        result, _ = _replace_outside(sql, re.compile(r"CURRENT_DATE", re.IGNORECASE), "TRUNC(SYSDATE)")
        return _replace_outside(result, re.compile(r"DATE_SUB\(TRUNC\(SYSDATE\),\s*(\d+)\)", re.IGNORECASE), r"TRUNC(SYSDATE) - \1")[0]
    if dialect == "tsql":
        result, _ = _replace_outside(sql, re.compile(r"CURRENT_DATE", re.IGNORECASE), "CAST(GETDATE() AS DATE)")
        return _replace_outside(result, re.compile(r"DATE_SUB\(CAST\(GETDATE\(\) AS DATE\),\s*(\d+)\)", re.IGNORECASE), r"DATEADD(DAY, -\1, CAST(GETDATE() AS DATE))")[0]
    if dialect == "postgres":
        return _replace_outside(sql, re.compile(r"DATE_SUB\(CURRENT_DATE,\s*(\d+)\)", re.IGNORECASE), r"CURRENT_DATE - INTERVAL '\1 days'")[0]
    return sql

NL2SQLGenerator._apply_dialect_adjustments = _apply_dialect_adjustments
