#!/usr/bin/env python3
"""Post-processor for dialect-specific SQL transformations.

Uses the rule engine for declarative transformations and handles
complex cases that require custom logic.
"""
import logging
import re
from typing import Tuple, List, Callable, Optional

from .rules import rule_engine, RuleEngine
from .function_call_scanner import replace_function_calls
from .p1_sql_scanner import mask_non_executable, executable_segments

logger = logging.getLogger(__name__)


def _simple_rownum_transform(sql: str) -> Tuple[str, Optional[str]]:
    """Convert simple Oracle ROWNUM <= N to LIMIT N with safety checks.

    Returns (transformed_sql, note_or_None). note is None when no
    ROWNUM predicate is found.  Unsafe query shapes (OR, UNION,
    ORDER BY, GROUP BY, HAVING, DISTINCT, multiple SELECT) are
    returned unchanged with a descriptive note.
    """
    masked = mask_non_executable(sql)
    upper = masked.upper()
    if "ROWNUM" not in upper:
        return sql, None
    if (
        len(re.findall(r"\bSELECT\b", upper)) != 1
        or any(token in upper for token in (
            " OR ", " UNION ", " INTERSECT ", " EXCEPT ",
            " ORDER BY ", " GROUP BY ", " HAVING ", " DISTINCT ",
        ))
    ):
        return sql, (
            "Skipped automatic ROWNUM conversion because query shape is not "
            "provably LIMIT-equivalent"
        )
    match = re.search(r"\bROWNUM\s*<=\s*(\d+)\b", masked, re.IGNORECASE)
    if not match:
        return sql, (
            "Skipped automatic ROWNUM conversion because query shape is not "
            "provably LIMIT-equivalent"
        )
    n = match.group(1)
    for pattern, replacement in [
        (re.compile(r"\s+AND\s+ROWNUM\s*<=\s*\d+\b", re.IGNORECASE), ""),
        (re.compile(r"\bWHERE\s+ROWNUM\s*<=\s*\d+\s+AND\s+", re.IGNORECASE), "WHERE "),
        (re.compile(r"\bWHERE\s+ROWNUM\s*<=\s*\d+\b", re.IGNORECASE), ""),
    ]:
        parts = []
        cursor = 0
        for start, end in executable_segments(sql):
            parts.append(sql[cursor:start])
            segment = sql[start:end]
            segment, count = pattern.subn(replacement, segment)
            parts.append(segment)
            cursor = end
        parts.append(sql[cursor:])
        result = "".join(parts)
        if result != sql:
            return result.rstrip(';').rstrip() + f" LIMIT {n}", (
                f"Converted simple ROWNUM <= {n} to LIMIT {n}"
            )
    return sql, (
        "Skipped automatic ROWNUM conversion because predicate shape was not "
        "safely removable"
    )


class PostProcessor:
    """Apply dialect-specific fixes after sqlglot transpilation."""

    def __init__(self, engine: RuleEngine = None):
        self.engine = engine or rule_engine

    def process(self, sql: str, source: str, target: str) -> Tuple[str, List[str]]:
        result = sql
        all_notes = []
        result, rule_notes = self.engine.apply_rules(result, source, target)
        all_notes.extend(rule_notes)
        result, custom_notes = self._apply_custom_transformations(result, source, target)
        all_notes.extend(custom_notes)
        warnings = self._check_warnings(sql, source, target)
        all_notes.extend(warnings)
        return result, all_notes

    def _apply_custom_transformations(self, sql: str, source: str, target: str) -> Tuple[str, List[str]]:
        result = sql
        notes = []
        if source == "oracle" and target != "oracle":
            result, decode_notes = self._convert_decode_to_case(result)
            notes.extend(decode_notes)
        if source == "mysql" and target == "postgres":
            result, date_notes = self._convert_mysql_date_format(result)
            notes.extend(date_notes)
        if source == "postgres" and target == "mysql":
            result, date_notes = self._convert_postgres_to_char(result)
            notes.extend(date_notes)
        if source == "tsql" and target in ("mysql", "postgres", "hive", "spark"):
            result, top_notes = self._convert_top_to_limit(result)
            notes.extend(top_notes)
        if source == "oracle" and target in ("mysql", "postgres", "hive", "spark"):
            result, rownum_notes = self._convert_rownum_to_limit(result)
            notes.extend(rownum_notes)
        if source == "mysql" and target == "postgres":
            result, gc_notes = self._fix_group_concat_default_separator(result)
            notes.extend(gc_notes)
        return result, notes

    def _replace_function_calls(self, sql: str, function_name: str, replacer: Callable[[str, str], str]) -> str:
        """Replace function calls using the shared quote/comment-aware scanner."""
        return replace_function_calls(sql, function_name, replacer)

    def _convert_decode_to_case(self, sql: str) -> Tuple[str, List[str]]:
        notes = []
        if "DECODE" not in mask_non_executable(sql).upper():
            return sql, notes

        def decode_to_case(args_str: str, original: str) -> str:
            args = self._parse_function_args(args_str)
            if len(args) < 3:
                return original
            col = args[0]
            pairs = args[1:]
            case_parts = []
            i = 0
            while i < len(pairs) - 1:
                value = pairs[i]
                comparator = "IS NULL" if value.strip().upper() == "NULL" else f"= {value}"
                case_parts.append(f"WHEN {col} {comparator} THEN {pairs[i + 1]}")
                i += 2
            default = pairs[-1] if len(pairs) % 2 == 1 else "NULL"
            return f"CASE {' '.join(case_parts)} ELSE {default} END"

        result = self._replace_function_calls(sql, "DECODE", decode_to_case)
        if result != sql:
            notes.append("Converted DECODE to CASE WHEN")
        return result, notes

    def _parse_function_args(self, args_str: str) -> List[str]:
        args = []
        current = ""
        depth = 0
        quote = False
        i = 0
        while i < len(args_str):
            char = args_str[i]
            if char == "'":
                current += char
                if quote and i + 1 < len(args_str) and args_str[i + 1] == "'":
                    current += args_str[i + 1]
                    i += 2
                    continue
                quote = not quote
            elif not quote and char == '(':
                depth += 1
                current += char
            elif not quote and char == ')':
                depth -= 1
                current += char
            elif not quote and char == ',' and depth == 0:
                args.append(current.strip())
                current = ""
            else:
                current += char
            i += 1
        if current.strip():
            args.append(current.strip())
        return args

    def _convert_mysql_date_format(self, sql: str) -> Tuple[str, List[str]]:
        notes = []
        if "DATE_FORMAT" not in mask_non_executable(sql).upper():
            return sql, notes
        def convert_format(args_str: str, original: str) -> str:
            args = self._parse_function_args(args_str)
            if len(args) != 2:
                return original
            expr, fmt = args
            if len(fmt) < 2 or fmt[0] != "'" or fmt[-1] != "'":
                return original
            fmt = fmt[1:-1]
            pg_fmt = fmt.replace('%Y', 'YYYY').replace('%y', 'YY').replace('%m', 'MM').replace('%d', 'DD').replace('%H', 'HH24').replace('%h', 'HH12').replace('%i', 'MI').replace('%s', 'SS').replace('%p', 'AM').replace('%W', 'Day').replace('%M', 'Month')
            return f"TO_CHAR({expr}, '{pg_fmt.replace(chr(39), chr(39) * 2)}')"
        result = self._replace_function_calls(sql, "DATE_FORMAT", convert_format)
        if result != sql:
            notes.append("Converted DATE_FORMAT to TO_CHAR")
        return result, notes

    def _convert_postgres_to_char(self, sql: str) -> Tuple[str, List[str]]:
        notes = []
        if "TO_CHAR" not in mask_non_executable(sql).upper():
            return sql, notes
        def convert_format(args_str: str, original: str) -> str:
            args = self._parse_function_args(args_str)
            if len(args) != 2:
                return original
            expr, fmt = args
            if len(fmt) < 2 or fmt[0] != "'" or fmt[-1] != "'":
                return original
            fmt = fmt[1:-1]
            my_fmt = fmt.replace('YYYY', '%Y').replace('YY', '%y').replace('MM', '%m').replace('DD', '%d').replace('HH24', '%H').replace('HH12', '%h').replace('HH', '%H').replace('MI', '%i').replace('SS', '%s').replace('AM', '%p').replace('Day', '%W').replace('Month', '%M')
            return f"DATE_FORMAT({expr}, '{my_fmt.replace(chr(39), chr(39) * 2)}')"
        result = self._replace_function_calls(sql, "TO_CHAR", convert_format)
        if result != sql:
            notes.append("Converted TO_CHAR to DATE_FORMAT")
        return result, notes

    @staticmethod
    def _single_rewrite(sql: str, pattern: str, replacement: Callable[[re.Match], str]):
        """Apply one regex match against scanner-masked SQL and splice into original text."""
        masked = mask_non_executable(sql)
        match = re.search(pattern, masked, re.IGNORECASE)
        if not match:
            return sql, None
        start, end = match.span()
        original_match = sql[start:end]
        proxy = re.match(pattern, original_match, re.IGNORECASE)
        if proxy is None:
            return sql, None
        return sql[:start] + replacement(proxy) + sql[end:], match

    def _convert_top_to_limit(self, sql: str) -> Tuple[str, List[str]]:
        masked = mask_non_executable(sql)
        match = re.search(r"SELECT\s+TOP\s+(\d+)", masked, re.IGNORECASE)
        if not match:
            return sql, []
        n = match.group(1)
        start, end = match.span()
        result = sql[:start] + "SELECT" + sql[end:]
        if "LIMIT" not in mask_non_executable(result).upper():
            if result.endswith("\n"):
                result += f" LIMIT {n}"
            else:
                line_comment = re.search(r"--[^\n]*$", result)
                if line_comment:
                    result = result[:line_comment.start()].rstrip() + f" LIMIT {n} " + result[line_comment.start():]
                else:
                    result = result.rstrip(';').rstrip() + f" LIMIT {n}"
        return result, [f"Converted TOP {n} to LIMIT {n}"]

    def _convert_rownum_to_limit(self, sql: str) -> Tuple[str, List[str]]:
        result, note = _simple_rownum_transform(sql)
        return result, ([note] if note else [])

    def _fix_group_concat_default_separator(self, sql: str) -> Tuple[str, List[str]]:
        masked = mask_non_executable(sql)
        match = re.search(r"GROUP_CONCAT\s*\((\w+)\)(?!\s+SEPARATOR)", masked, re.IGNORECASE)
        if not match:
            return sql, []
        col = match.group(1)
        start, end = match.span()
        result = sql[:start] + f"STRING_AGG({col}::TEXT, ',')" + sql[end:]
        return result, ["Converted GROUP_CONCAT to STRING_AGG with default separator"]

    def _check_warnings(self, sql: str, source: str, target: str) -> List[str]:
        warnings = []
        sql_upper = mask_non_executable(sql).upper()
        if source == "hive" and "INSERT OVERWRITE" in sql_upper and target in ("mysql", "postgres", "tsql", "oracle"):
            warnings.append(f"WARNING: INSERT OVERWRITE not supported in {target}. Use TRUNCATE + INSERT or MERGE instead.")
        if source == "oracle" and "CONNECT BY" in sql_upper and target in ("hive", "postgres", "mysql"):
            warnings.append("WARNING: CONNECT BY requires manual conversion to WITH RECURSIVE CTE")
        if source == "hive" and target in ("mysql", "postgres", "oracle", "tsql") and ("DISTRIBUTE BY" in sql_upper or "CLUSTER BY" in sql_upper):
            warnings.append("WARNING: DISTRIBUTE BY/CLUSTER BY are Hive-specific hints, removed in target")
        if any(kw in sql_upper for kw in ["CREATE PROCEDURE", "CREATE FUNCTION", "BEGIN", "DECLARE"]):
            warnings.append("WARNING: Procedural code detected. Stored procedure syntax varies significantly between databases.")
        if "MATERIALIZED VIEW" in sql_upper:
            warnings.append("WARNING: Materialized view syntax and refresh mechanisms vary by database.")
        return warnings

    def get_stats(self) -> dict:
        return {
            "rule_engine": self.engine.get_stats(),
            "custom_handlers": ["DECODE to CASE", "DATE_FORMAT conversion", "TOP to LIMIT", "ROWNUM to LIMIT", "GROUP_CONCAT separator fix"]
        }
