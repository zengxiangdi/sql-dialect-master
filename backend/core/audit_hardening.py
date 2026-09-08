"""Second-pass semantic and security hardening for SQL Dialect Master."""

from typing import Callable, Optional, Tuple
import re

import sqlglot
from sqlglot import exp

from .config import DANGEROUS_SQL_PATTERNS, SUPPORTED_DIALECTS, WARNING_SQL_PATTERNS, settings
from .nl2sql import NL2SQLGenerator
from .parser import SQLParser
from .post_processor import PostProcessor
from .rules import TransformRule
from .transpiler import SQLTranspiler


def _mask_non_executable(sql: str) -> str:
    """Mask strings, quoted identifiers, and comments while preserving layout."""
    out = list(sql)
    i = 0
    n = len(sql)
    quote: Optional[str] = None
    while i < n:
        ch = sql[i]
        if quote is None:
            if ch in ("'", '"', '`'):
                quote = ch; out[i] = " "; i += 1; continue
            if ch == '[':
                quote = ']'; out[i] = " "; i += 1; continue
            if ch == '-' and i + 1 < n and sql[i + 1] == '-':
                out[i] = out[i + 1] = ' '; i += 2
                while i < n and sql[i] not in '\r\n': out[i] = ' '; i += 1
                continue
            if ch == '/' and i + 1 < n and sql[i + 1] == '*':
                out[i] = out[i + 1] = ' '; i += 2
                while i < n:
                    if i + 1 < n and sql[i] == '*' and sql[i + 1] == '/':
                        out[i] = out[i + 1] = ' '; i += 2; break
                    if sql[i] not in '\r\n': out[i] = ' '
                    i += 1
                continue
            i += 1; continue
        out[i] = ch if ch in '\r\n' else ' '
        if ch == quote:
            if i + 1 < n and sql[i + 1] == quote:
                out[i + 1] = ' '; i += 2; continue
            quote = None
        elif quote == "'" and ch == '\\' and i + 1 < n:
            out[i + 1] = ' '; i += 2
        i += 1
    return ''.join(out)


def _replace_outside_sql_literals(sql: str, pattern: re.Pattern, replacement: str | Callable[[re.Match], str]) -> Tuple[str, int]:
    """Apply a regex only to executable SQL, leaving strings/comments unchanged."""
    parts = []; start = 0; i = 0; n = len(sql); quote: Optional[str] = None; changed = 0
    def replace_segment(segment: str) -> str:
        nonlocal changed
        result, count = pattern.subn(replacement, segment); changed += count; return result
    while i < n:
        ch = sql[i]
        if quote is None:
            if ch in ("'", '"', '`') or ch == '[':
                if start < i: parts.append(replace_segment(sql[start:i]))
                quote = ']' if ch == '[' else ch; i += 1; continue
            if ch == '-' and i + 1 < n and sql[i + 1] == '-':
                if start < i: parts.append(replace_segment(sql[start:i]))
                j = i + 2
                while j < n and sql[j] not in '\r\n': j += 1
                parts.append(sql[i:j]); i = j; start = i; continue
            if ch == '/' and i + 1 < n and sql[i + 1] == '*':
                if start < i: parts.append(replace_segment(sql[start:i]))
                j = i + 2
                while j + 1 < n and not (sql[j] == '*' and sql[j + 1] == '/'): j += 1
                j = min(n, j + 2); parts.append(sql[i:j]); i = j; start = i; continue
            i += 1; continue
        i += 1
        if ch == quote:
            if i < n and sql[i] == quote: i += 1; continue
            parts.append(sql[start:i]); start = i; quote = None
        elif quote == "'" and ch == '\\' and i < n: i += 1
    if start < n:
        parts.append(replace_segment(sql[start:]) if quote is None else sql[start:])
    return ''.join(parts), changed


def _find_top_level_keyword(text: str, keyword: str) -> int:
    wanted = keyword.upper(); depth = 0; quote: Optional[str] = None; i = 0
    while i < len(text):
        ch = text[i]
        if quote is not None:
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote: i += 2; continue
                quote = None
            elif quote == "'" and ch == '\\' and i + 1 < len(text): i += 2; continue
            i += 1; continue
        if ch in ("'", '"', '`'): quote = ch; i += 1; continue
        if ch == '(': depth += 1; i += 1; continue
        if ch == ')': depth = max(0, depth - 1); i += 1; continue
        if depth == 0 and text[i:i + len(wanted)].upper() == wanted:
            before = text[i - 1] if i else ' '; after = text[i + len(wanted)] if i + len(wanted) < len(text) else ' '
            if not (before.isalnum() or before == '_') and not (after.isalnum() or after == '_'): return i
        i += 1
    return -1


def _dml_without_where(sql: str):
    try:
        statements = sqlglot.parse(sql)
    except Exception:
        return None
    findings = []
    for statement in statements:
        for node in statement.walk():
            if isinstance(node, (exp.Update, exp.Delete)) and node.args.get('where') is None:
                findings.append('UPDATE' if isinstance(node, exp.Update) else 'DELETE')
    return findings


def _validate_security_hardened(self, sql: str):
    result = {"blocked": False, "reason": None, "warnings": []}
    masked = _mask_non_executable(sql)
    try:
        if len(sqlglot.parse(sql)) > 1:
            message = "Multiple SQL statements detected"
            if settings.security_block_dangerous:
                result["blocked"] = True; result["reason"] = message; return result
            result["warnings"].append(f"🔒 Security: {message}")
    except Exception:
        pass
    for pattern, message in DANGEROUS_SQL_PATTERNS:
        if pattern.search(masked):
            if settings.security_block_dangerous:
                result["blocked"] = True; result["reason"] = message; return result
            result["warnings"].append(f"🔒 Security: {message}")
    for operation in _dml_without_where(sql) or []:
        result["warnings"].append(f"⚠️ {operation} without WHERE clause - may affect all rows")
    for pattern, message in WARNING_SQL_PATTERNS:
        if pattern.search(masked): result["warnings"].append(f"⚠️ {message}")
    return result


SQLTranspiler._validate_security = _validate_security_hardened


def _generate_warnings_hardened(self, sql: str, source: str, target: str):
    masked = _mask_non_executable(sql); upper = masked.upper(); warnings = []
    if 'DROP TABLE' in upper or 'TRUNCATE' in upper: warnings.append('⚠️ Dangerous operation detected: DROP/TRUNCATE')
    for operation in _dml_without_where(sql) or []: warnings.append(f'⚠️ {operation} without WHERE clause - will affect all rows')
    if 'SELECT *' in upper: warnings.append('💡 Consider specifying columns instead of SELECT *')
    if 'CROSS JOIN' in upper: warnings.append('💡 CROSS JOIN can produce large result sets')
    if len(re.findall(r'\bJOIN\b', upper)) > 5: warnings.append('💡 Query has many JOINs - consider query optimization')
    if source == 'hive' and target in ['mysql', 'postgres', 'oracle']:
        if 'DISTRIBUTE BY' in upper or 'CLUSTER BY' in upper: warnings.append('⚠️ DISTRIBUTE BY/CLUSTER BY are Hive-specific hints, removed in target')
        if 'SORT BY' in upper: warnings.append('⚠️ SORT BY is Hive-specific, converted to ORDER BY')
    if source in ['hive', 'spark'] and target in ['mysql', 'postgres'] and ('COLLECT_LIST' in upper or 'COLLECT_SET' in upper):
        warnings.append('💡 Array aggregation converted - verify result format')
    return warnings


SQLTranspiler._generate_warnings = _generate_warnings_hardened


def _rownum_to_limit_safe(self, sql: str):
    masked = _mask_non_executable(sql); upper = masked.upper()
    if 'ROWNUM' not in upper: return sql, []
    if len(re.findall(r'\bSELECT\b', upper)) != 1 or any(token in upper for token in (' OR ', ' UNION ', ' INTERSECT ', ' EXCEPT ', ' ORDER BY ', ' GROUP BY ', ' HAVING ', ' DISTINCT ')):
        return sql, ['Skipped automatic ROWNUM conversion because query shape is not provably LIMIT-equivalent']
    match = re.search(r'\bROWNUM\s*<=\s*(\d+)\b', masked, re.IGNORECASE)
    if not match or not re.search(r'\bWHERE\b', masked, re.IGNORECASE):
        return sql, ['Skipped automatic ROWNUM conversion because query shape is not provably LIMIT-equivalent']
    n = match.group(1)
    result, count = _replace_outside_sql_literals(sql, re.compile(r'\s+AND\s+ROWNUM\s*<=\s*\d+\b', re.IGNORECASE), '')
    if not count:
        result, count = _replace_outside_sql_literals(sql, re.compile(r'\bWHERE\s+ROWNUM\s*<=\s*\d+\s+AND\s+', re.IGNORECASE), 'WHERE ')
    if not count:
        result, count = _replace_outside_sql_literals(sql, re.compile(r'\bWHERE\s+ROWNUM\s*<=\s*\d+\b', re.IGNORECASE), '')
    if not count: return sql, ['Skipped automatic ROWNUM conversion because predicate shape was not safely removable']
    result = result.strip()
    if re.search(r'\bLIMIT\b', _mask_non_executable(result), re.IGNORECASE) is None: result = result.rstrip(';').rstrip() + f' LIMIT {n}'
    return result, [f'Converted simple ROWNUM <= {n} to LIMIT {n}']


PostProcessor._convert_rownum_to_limit = _rownum_to_limit_safe


def _convert_group_concat(args_str: str, original: str) -> str:
    args = args_str.strip(); sep_pos = _find_top_level_keyword(args, 'SEPARATOR'); separator = "','"; before_sep = args
    if sep_pos >= 0: before_sep = args[:sep_pos].rstrip(); separator = args[sep_pos + 9:].strip() or separator
    order_pos = _find_top_level_keyword(before_sep, 'ORDER BY'); order_expr = None; expr_part = before_sep
    if order_pos >= 0: expr_part = before_sep[:order_pos].rstrip(); order_expr = before_sep[order_pos + 8:].strip()
    distinct = False
    if expr_part[:9].upper() == 'DISTINCT ': distinct = True; expr_part = expr_part[9:].strip()
    if not expr_part: return original
    prefix = 'DISTINCT ' if distinct else ''
    converted = f'STRING_AGG({prefix}({expr_part})::TEXT, {separator}'
    if order_expr: converted += f' ORDER BY {order_expr}'
    return converted + ')'


_original_process = PostProcessor.process


def _process_group_concat_hardened(self, sql: str, source: str, target: str):
    if source.lower() == 'mysql' and target.lower() == 'postgres' and 'GROUP_CONCAT' in _mask_non_executable(sql).upper():
        protected, count = _replace_outside_sql_literals(sql, re.compile(r'GROUP_CONCAT\s*\(', re.IGNORECASE), '__SDM_GROUP_CONCAT__(')
        if count:
            protected = self._replace_function_calls(protected, '__SDM_GROUP_CONCAT__', _convert_group_concat)
            return _original_process(self, protected, source, target)
    result, notes = _original_process(self, sql, source, target)
    if source.lower() == 'mysql' and target.lower() == 'postgres':
        result = re.sub(r'STRING_AGG\(([^()]+)::TEXT,\s*\'\'\)', r"STRING_AGG(\1::TEXT, ',')", result, flags=re.IGNORECASE)
    return result, notes


PostProcessor.process = _process_group_concat_hardened


def _apply_rule_quote_aware(self, sql: str):
    if not self.enabled: return sql, False
    pattern = getattr(self, '_compiled_pattern', None) or re.compile(self.pattern, re.IGNORECASE)
    self._compiled_pattern = pattern
    result, count = _replace_outside_sql_literals(sql, pattern, self.replacement)
    return result, count > 0


TransformRule.apply = _apply_rule_quote_aware


def _apply_dialect_adjustments_safe(self, sql: str, dialect: str):
    if dialect == 'oracle':
        adjusted, _ = _replace_outside_sql_literals(sql, re.compile(r'CURRENT_DATE', re.IGNORECASE), 'TRUNC(SYSDATE)')
        adjusted, _ = _replace_outside_sql_literals(adjusted, re.compile(r'DATE_SUB\(TRUNC\(SYSDATE\),\s*(\d+)\)', re.IGNORECASE), r'TRUNC(SYSDATE) - \1')
        return adjusted
    if dialect == 'tsql':
        adjusted, _ = _replace_outside_sql_literals(sql, re.compile(r'CURRENT_DATE', re.IGNORECASE), 'CAST(GETDATE() AS DATE)')
        adjusted, _ = _replace_outside_sql_literals(adjusted, re.compile(r'DATE_SUB\(CAST\(GETDATE\(\) AS DATE\),\s*(\d+)\)', re.IGNORECASE), r'DATEADD(DAY, -\1, CAST(GETDATE() AS DATE))')
        return adjusted
    if dialect == 'postgres':
        adjusted, _ = _replace_outside_sql_literals(sql, re.compile(r'DATE_SUB\(CURRENT_DATE,\s*(\d+)\)', re.IGNORECASE), r"CURRENT_DATE - INTERVAL '\1 days'")
        return adjusted
    return sql


NL2SQLGenerator._apply_dialect_adjustments = _apply_dialect_adjustments_safe
