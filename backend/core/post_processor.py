#!/usr/bin/env python3
"""Post-processor for dialect-specific SQL transformations.

Uses the rule engine for declarative transformations and handles
complex cases that require custom logic.
"""
import logging
import re
from typing import Tuple, List, Callable

from .rules import rule_engine, RuleEngine

# Configure module logger
logger = logging.getLogger(__name__)


class PostProcessor:
    """Apply dialect-specific fixes after sqlglot transpilation.
    
    Uses a combination of:
    1. Rule engine for declarative pattern-based transformations
    2. Custom handlers for complex transformations
    """
    
    def __init__(self, engine: RuleEngine = None):
        """Initialize with rule engine.
        
        Args:
            engine: Rule engine to use. Uses global engine if None.
        """
        self.engine = engine or rule_engine
    
    def process(self, sql: str, source: str, target: str) -> Tuple[str, List[str]]:
        """Apply post-processing rules."""
        result = sql
        all_notes = []

        # GROUP_CONCAT must be handled before declarative rules.  The rule
        # engine's legacy pattern only handles a bare identifier and would
        # otherwise turn a missing separator into an empty string separator.
        if source == "mysql" and target == "postgres":
            result, gc_notes = self._convert_group_concat(result)
            all_notes.extend(gc_notes)

        result, rule_notes = self.engine.apply_rules(result, source, target)
        all_notes.extend(rule_notes)

        result, custom_notes = self._apply_custom_transformations(result, source, target)
        all_notes.extend(custom_notes)

        warnings = self._check_warnings(sql, source, target)
        all_notes.extend(warnings)
        return result, all_notes
    
    def _apply_custom_transformations(self, sql: str, source: str, target: str) -> Tuple[str, List[str]]:
        """Apply complex transformations that need custom logic."""
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
        
        return result, notes

    def _replace_function_calls(
        self,
        sql: str,
        function_name: str,
        replacer: Callable[[str, str], str],
    ) -> str:
        """Replace complete function calls with balanced parentheses.

        The scanner is quote-aware so text inside SQL string literals is never
        treated as executable function syntax.
        """
        upper_name = function_name.upper()
        name_len = len(function_name)
        result = []
        i = 0
        quote = False
        length = len(sql)

        while i < length:
            char = sql[i]
            if char == "'":
                result.append(char)
                if quote and i + 1 < length and sql[i + 1] == "'":
                    result.append(sql[i + 1])
                    i += 2
                    continue
                quote = not quote
                i += 1
                continue

            if not quote and sql[i:i + name_len].upper() == upper_name:
                name_end = i + name_len
                if i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == '_'):
                    j = name_end
                    while j < length and sql[j].isspace():
                        j += 1
                    if j < length and sql[j] == '(':
                        depth = 0
                        inner_quote = False
                        k = j
                        while k < length:
                            inner = sql[k]
                            if inner == "'":
                                if inner_quote and k + 1 < length and sql[k + 1] == "'":
                                    k += 2
                                    continue
                                inner_quote = not inner_quote
                            elif not inner_quote:
                                if inner == '(':
                                    depth += 1
                                elif inner == ')':
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
                        continue

            result.append(char)
            i += 1

        return ''.join(result)
    
    def _convert_decode_to_case(self, sql: str) -> Tuple[str, List[str]]:
        """Convert Oracle DECODE to CASE WHEN."""
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
                case_parts.append(f"WHEN {col} = {pairs[i]} THEN {pairs[i+1]}")
                i += 2
            
            if len(pairs) % 2 == 1:
                default = pairs[-1]
            else:
                default = "NULL"
            
            return f"CASE {' '.join(case_parts)} ELSE {default} END"
        
        result = self._replace_function_calls(sql, "DECODE", decode_to_case)
        
        if result != sql:
            notes.append("Converted DECODE to CASE WHEN")
        
        return result, notes
    
    def _parse_function_args(self, args_str: str) -> List[str]:
        """Parse function arguments handling nested parentheses and quotes."""
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
        """Convert MySQL DATE_FORMAT to PostgreSQL TO_CHAR."""
        notes = []
        
        if "DATE_FORMAT" not in sql.upper():
            return sql, notes
        
        def convert_format(args_str: str, original: str) -> str:
            args = self._parse_function_args(args_str)
            if len(args) != 2:
                return original
            expr, fmt = args
            if len(fmt) < 2 or fmt[0] != "'" or fmt[-1] != "'":
                return original
            fmt = fmt[1:-1]
            pg_fmt = fmt
            pg_fmt = pg_fmt.replace('%Y', 'YYYY')
            pg_fmt = pg_fmt.replace('%y', 'YY')
            pg_fmt = pg_fmt.replace('%m', 'MM')
            pg_fmt = pg_fmt.replace('%d', 'DD')
            pg_fmt = pg_fmt.replace('%H', 'HH24')
            pg_fmt = pg_fmt.replace('%h', 'HH12')
            pg_fmt = pg_fmt.replace('%i', 'MI')
            pg_fmt = pg_fmt.replace('%s', 'SS')
            pg_fmt = pg_fmt.replace('%p', 'AM')
            pg_fmt = pg_fmt.replace('%W', 'Day')
            pg_fmt = pg_fmt.replace('%M', 'Month')
            return f"TO_CHAR({expr}, '{pg_fmt.replace(chr(39), chr(39) * 2)}')"
        
        result = self._replace_function_calls(sql, "DATE_FORMAT", convert_format)
        
        if result != sql:
            notes.append("Converted DATE_FORMAT to TO_CHAR")
        
        return result, notes
    
    def _convert_postgres_to_char(self, sql: str) -> Tuple[str, List[str]]:
        """Convert PostgreSQL TO_CHAR to MySQL DATE_FORMAT."""
        notes = []
        
        if "TO_CHAR" not in sql.upper():
            return sql, notes
        
        def convert_format(args_str: str, original: str) -> str:
            args = self._parse_function_args(args_str)
            if len(args) != 2:
                return original
            expr, fmt = args
            if len(fmt) < 2 or fmt[0] != "'" or fmt[-1] != "'":
                return original
            fmt = fmt[1:-1]
            my_fmt = fmt
            my_fmt = my_fmt.replace('YYYY', '%Y')
            my_fmt = my_fmt.replace('YY', '%y')
            my_fmt = my_fmt.replace('MM', '%m')
            my_fmt = my_fmt.replace('DD', '%d')
            my_fmt = my_fmt.replace('HH24', '%H')
            my_fmt = my_fmt.replace('HH12', '%h')
            my_fmt = my_fmt.replace('HH', '%H')
            my_fmt = my_fmt.replace('MI', '%i')
            my_fmt = my_fmt.replace('SS', '%s')
            my_fmt = my_fmt.replace('AM', '%p')
            my_fmt = my_fmt.replace('Day', '%W')
            my_fmt = my_fmt.replace('Month', '%M')
            return f"DATE_FORMAT({expr}, '{my_fmt.replace(chr(39), chr(39) * 2)}')"
        
        result = self._replace_function_calls(sql, "TO_CHAR", convert_format)
        
        if result != sql:
            notes.append("Converted TO_CHAR to DATE_FORMAT")
        
        return result, notes
    
    def _convert_top_to_limit(self, sql: str) -> Tuple[str, List[str]]:
        """Convert SQL Server TOP to LIMIT."""
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
        """Convert Oracle ROWNUM to LIMIT."""
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

    def _convert_group_concat(self, sql: str) -> Tuple[str, List[str]]:
        """Convert MySQL GROUP_CONCAT using a quote/parenthesis-aware scanner."""
        notes = []

        def convert(args_str: str, original: str) -> str:
            args = args_str.strip()
            separator = ","
            separator_match = re.search(r"\s+SEPARATOR\s+('(?:''|[^'])*')\s*$", args, re.IGNORECASE)
            if separator_match:
                separator = separator_match.group(1)[1:-1].replace("''", "'")
                core = args[:separator_match.start()].rstrip()
            else:
                core = args

            order_expr = None
            depth = 0
            quote = False
            order_pos = None
            i = 0
            while i < len(core):
                char = core[i]
                if char == "'":
                    if quote and i + 1 < len(core) and core[i + 1] == "'":
                        i += 2
                        continue
                    quote = not quote
                elif not quote:
                    if char == '(':
                        depth += 1
                    elif char == ')':
                        depth -= 1
                    elif depth == 0 and core[i:i + 8].upper() == "ORDER BY":
                        before = core[i - 1] if i else " "
                        after = core[i + 8] if i + 8 < len(core) else " "
                        if before.isspace() and after.isspace():
                            order_pos = i
                            break
                i += 1

            if order_pos is not None:
                order_expr = core[order_pos + 8:].strip()
                core = core[:order_pos].rstrip()

            distinct = False
            if core.upper().startswith("DISTINCT "):
                distinct = True
                core = core[9:].strip()

            if not core:
                return original

            if distinct:
                value_expr = f"DISTINCT ({core})::TEXT"
            else:
                value_expr = f"{core}::TEXT"

            result = f"STRING_AGG({value_expr}, '{separator.replace(chr(39), chr(39) * 2)}'"
            if order_expr:
                result += f" ORDER BY {order_expr}"
            return result + ")"

        result = self._replace_function_calls(sql, "GROUP_CONCAT", convert)
        if result != sql:
            notes.append("Converted GROUP_CONCAT to STRING_AGG")
        return result, notes
    
    def _check_warnings(self, sql: str, source: str, target: str) -> List[str]:
        """Check for constructs that may need manual attention."""
        warnings = []
        sql_upper = sql.upper()
        
        if source == "hive" and "INSERT OVERWRITE" in sql_upper:
            if target in ("mysql", "postgres", "tsql", "oracle"):
                warnings.append(
                    f"WARNING: INSERT OVERWRITE not supported in {target}. "
                    "Use TRUNCATE + INSERT or MERGE instead."
                )
        
        if source == "oracle" and "CONNECT BY" in sql_upper:
            if target in ("hive", "postgres", "mysql"):
                warnings.append(
                    "WARNING: CONNECT BY requires manual conversion to WITH RECURSIVE CTE"
                )
        
        if source == "hive" and target in ("mysql", "postgres", "oracle", "tsql"):
            if "DISTRIBUTE BY" in sql_upper or "CLUSTER BY" in sql_upper:
                warnings.append(
                    "WARNING: DISTRIBUTE BY/CLUSTER BY are Hive-specific hints, removed in target"
                )
        
        if any(kw in sql_upper for kw in ["CREATE PROCEDURE", "CREATE FUNCTION", "BEGIN", "DECLARE"]):
            warnings.append(
                "WARNING: Procedural code detected. Stored procedure syntax varies significantly between databases."
            )
        
        if "MATERIALIZED VIEW" in sql_upper:
            warnings.append(
                "WARNING: Materialized view syntax and refresh mechanisms vary by database."
            )
        
        return warnings
    
    def get_stats(self) -> dict:
        """Get post-processor statistics."""
        return {
            "rule_engine": self.engine.get_stats(),
            "custom_handlers": [
                "DECODE to CASE",
                "DATE_FORMAT conversion",
                "TOP to LIMIT",
                "ROWNUM to LIMIT",
                "GROUP_CONCAT to STRING_AGG"
            ]
        }
