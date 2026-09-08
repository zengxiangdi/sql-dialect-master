#!/usr/bin/env python3
"""Post-processor for dialect-specific SQL transformations.

Uses the rule engine for declarative transformations and handles
complex cases that require custom logic.
"""
import logging
import re
from typing import Tuple, List, Callable

from .rules import rule_engine, RuleEngine

logger = logging.getLogger(__name__)


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
        """Replace complete function calls, preserving nested parentheses and quoted strings."""
        upper_name = function_name.upper()
        result = []
        i = 0
        length = len(sql)
        while i < length:
            if sql[i:i + len(function_name)].upper() != upper_name:
                result.append(sql[i])
                i += 1
                continue

            name_end = i + len(function_name)
            if i > 0 and (sql[i - 1].isalnum() or sql[i - 1] == '_'):
                result.append(sql[i])
                i += 1
                continue

            j = name_end
            while j < length and sql[j].isspace():
                j += 1
            if j >= length or sql[j] != '(':
                result.append(sql[i])
                i += 1
                continue

            depth = 0
            quote = False
            k = j
            while k < length:
                ch = sql[k]
                if ch == "'":
                    if quote and k + 1 < length and sql[k + 1] == "'":
                        k += 2
                        continue
                    quote = not quote
                elif not quote:
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth -= 1
                        if depth == 0:
                            args = sql[j + 1:k]
                            result.append(replacer(args, sql[i:k + 1]))
                            i = k + 1
                            break
                k += 1
            else:
                result.append(sql[i:])
                break
        return ''.join(result)

    def _convert_decode_to_case(self, sql: str) -> Tuple[str, List[str]]:
        notes = []
        if "DECODE" not in sql.upper():
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
                case_parts.append(f"WHEN {col} = {pairs[i]} THEN {pairs[i + 1]}")
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
                if quote and i + 1 < len(args_str) and args_str[i + 1] == "'":
                    current += "''"
                    i += 2
                    continue
                quote = not quote
                current += char
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
        if "DATE_FORMAT" not in sql.upper():
            return sql, notes

        def convert_format(args_str: str, original: str) -> str:
            args = self._parse_function_args(args_str)
            if len(args) != 2 or not (len(args[1]) >= 2 and args[1][0] == "'" and args[1][-1] == "'"):
                return original
            expr, fmt = args
            fmt = fmt[1:-1]
            pg_fmt = fmt.replace('%Y', 'YYYY').replace('%y', 'YY').replace('%m', 'MM').replace('%d', 'DD')
            pg_fmt = pg_fmt.replace('%H', 'HH24').replace('%h', 'HH12').replace('%i', 'MI').replace('%s', 'SS')
            pg_fmt = pg_fmt.replace('%p', 'AM').replace('%W', 'Day').replace('%M', 'Month')
            escaped_fmt = pg_fmt.replace("'", "''")
            return f"TO_CHAR({expr}, '{escaped_fmt}')"

        result = self._replace_function_calls(sql, "DATE_FORMAT", convert_format)
        if result != sql:
            notes.append("Converted DATE_FORMAT to TO_CHAR")
        return result, notes

    def _convert_postgres_to_char(self, sql: str) -> Tuple[str, List[str]]:
        notes = []
        if "TO_CHAR" not in sql.upper():
            return sql, notes

        def convert_format(args_str: str, original: str) -> str:
            args = self._parse_function_args(args_str)
            if len(args) != 2 or not (len(args[1]) >= 2 and args[1][0] == "'" and args[1][-1] == "'"):
                return original
            expr, fmt = args
            fmt = fmt[1:-1]
            my_fmt = fmt.replace('YYYY', '%Y').replace('YY', '%y').replace('MM', '%m').replace('DD', '%d')
            my_fmt = my_fmt.replace('HH24', '%H').replace('HH12', '%h').replace('HH', '%H').replace('MI', '%i')
            my_fmt = my_fmt.replace('SS', '%s').replace('AM', '%p').replace('Day', '%W').replace('Month', '%M')
            escaped_fmt = my_fmt.replace("'", "''")
            return f"DATE_FORMAT({expr}, '{escaped_fmt}')"

        result = self._replace_function_calls(sql, "TO_CHAR", convert_format)
        if result != sql:
            notes.append("Converted TO_CHAR to DATE_FORMAT")
        return result, notes

    def _convert_top_to_limit(self, sql: str) -> Tuple[str, List[str]]:
        notes = []
        match = re.search(r"SELECT\s+TOP\s+(\d+)", sql, re.IGNORECASE)
        if not match:
            return sql, notes
        n = match.group(1)
        result = re.sub(r"SELECT\s+TOP\s+\d+", "SELECT", sql, flags=re.IGNORECASE)
        if "LIMIT" not in result.upper():
            result = result.rstrip(';').rstrip() + f" LIMIT {n}"
        notes.append(f"Converted TOP {n} to LIMIT {n}")
        return result, notes

    def _convert_rownum_to_limit(self, sql: str) -> Tuple[str, List[str]]:
        notes = []
        if "ROWNUM" not in sql.upper():
            return sql, notes
        match = re.search(r"ROWNUM\s*<=?\s*(\d+)", sql, re.IGNORECASE)
        if not match:
            return sql, notes
        n = match.group(1)
        result = sql
        result = re.sub(r"\s*AND\s+ROWNUM\s*<=?\s*\d+", "", result, flags=re.IGNORECASE)
        result = re.sub(r"\s*WHERE\s+ROWNUM\s*<=?\s*\d+", "", result, flags=re.IGNORECASE)
        if "LIMIT" not in result.upper():
            result = result.rstrip(';').rstrip() + f" LIMIT {n}"
        notes.append(f"Converted ROWNUM to LIMIT {n}")
        return result, notes

    def _fix_group_concat_default_separator(self, sql: str) -> Tuple[str, List[str]]:
        notes = []
        pattern = r"GROUP_CONCAT\s*\((\w+)\)(?!\s+SEPARATOR)"

        def add_default_separator(match):
            col = match.group(1)
            return f"STRING_AGG({col}::TEXT, ',')"

        result = re.sub(pattern, add_default_separator, sql, flags=re.IGNORECASE)
        if result != sql:
            notes.append("Converted GROUP_CONCAT to STRING_AGG with default separator")
        return result, notes

    def _check_warnings(self, sql: str, source: str, target: str) -> List[str]:
        warnings = []
        sql_upper = sql.upper()
        if source == "hive" and "INSERT OVERWRITE" in sql_upper and target in ("mysql", "postgres", "tsql", "oracle"):
            warnings.append(f"WARNING: INSERT OVERWRITE not supported in {target}. Use TRUNCATE + INSERT or MERGE instead.")
        if source == "oracle" and "CONNECT BY" in sql_upper and target in ("hive", "postgres", "mysql"):
            warnings.append("WARNING: CONNECT BY requires manual conversion to WITH RECURSIVE CTE")
        if source == "hive" and target in ("mysql", "postgres", "oracle", "tsql"):
            if "DISTRIBUTE BY" in sql_upper or "CLUSTER BY" in sql_upper:
                warnings.append("WARNING: DISTRIBUTE BY/CLUSTER BY are Hive-specific hints, removed in target")
        if any(kw in sql_upper for kw in ["CREATE PROCEDURE", "CREATE FUNCTION", "BEGIN", "DECLARE"]):
            warnings.append("WARNING: Procedural code detected. Stored procedure syntax varies significantly between databases.")
        if "MATERIALIZED VIEW" in sql_upper:
            warnings.append("WARNING: Materialized view syntax and refresh mechanisms vary by database.")
        return warnings

    def get_stats(self) -> dict:
        return {
            "rule_engine": self.engine.get_stats(),
            "custom_handlers": [
                "DECODE to CASE",
                "DATE_FORMAT conversion",
                "TOP to LIMIT",
                "ROWNUM to LIMIT",
                "GROUP_CONCAT separator fix"
            ]
        }
