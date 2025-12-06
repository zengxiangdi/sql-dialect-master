#!/usr/bin/env python3
"""Post-processor for dialect-specific SQL transformations.

Uses the rule engine for declarative transformations and handles
complex cases that require custom logic.
"""
import logging
import re
from typing import Tuple, List

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
        """Apply post-processing rules.
        
        Args:
            sql: SQL to process
            source: Source dialect
            target: Target dialect
            
        Returns:
            Tuple of (processed_sql, list_of_notes)
        """
        result = sql
        all_notes = []
        
        # Step 1: Apply rule engine transformations
        result, rule_notes = self.engine.apply_rules(result, source, target)
        all_notes.extend(rule_notes)
        
        # Step 2: Apply complex transformations that need custom logic
        result, custom_notes = self._apply_custom_transformations(result, source, target)
        all_notes.extend(custom_notes)
        
        # Step 3: Add warnings for unsupported constructs
        warnings = self._check_warnings(sql, source, target)
        all_notes.extend(warnings)
        
        return result, all_notes
    
    def _apply_custom_transformations(self, sql: str, source: str, target: str) -> Tuple[str, List[str]]:
        """Apply complex transformations that need custom logic.
        
        Args:
            sql: SQL to transform
            source: Source dialect
            target: Target dialect
            
        Returns:
            Tuple of (transformed_sql, list_of_notes)
        """
        result = sql
        notes = []
        
        # Oracle DECODE → CASE WHEN (complex transformation)
        if source == "oracle" and target != "oracle":
            result, decode_notes = self._convert_decode_to_case(result)
            notes.extend(decode_notes)
        
        # MySQL DATE_FORMAT → PostgreSQL TO_CHAR
        if source == "mysql" and target == "postgres":
            result, date_notes = self._convert_mysql_date_format(result)
            notes.extend(date_notes)
        
        # PostgreSQL TO_CHAR → MySQL DATE_FORMAT
        if source == "postgres" and target == "mysql":
            result, date_notes = self._convert_postgres_to_char(result)
            notes.extend(date_notes)
        
        # SQL Server TOP → LIMIT
        if source == "tsql" and target in ("mysql", "postgres", "hive", "spark"):
            result, top_notes = self._convert_top_to_limit(result)
            notes.extend(top_notes)
        
        # Oracle ROWNUM → LIMIT
        if source == "oracle" and target in ("mysql", "postgres", "hive", "spark"):
            result, rownum_notes = self._convert_rownum_to_limit(result)
            notes.extend(rownum_notes)
        
        # GROUP_CONCAT with default separator fix
        if source == "mysql" and target == "postgres":
            result, gc_notes = self._fix_group_concat_default_separator(result)
            notes.extend(gc_notes)
        
        return result, notes
    
    def _convert_decode_to_case(self, sql: str) -> Tuple[str, List[str]]:
        """Convert Oracle DECODE to CASE WHEN."""
        notes = []
        
        if "DECODE" not in sql.upper():
            return sql, notes
        
        def decode_to_case(match):
            args_str = match.group(1)
            # Parse arguments carefully handling nested parentheses
            args = self._parse_function_args(args_str)
            
            if len(args) < 3:
                return match.group(0)
            
            col = args[0]
            pairs = args[1:]
            
            # Build CASE expression
            case_parts = []
            i = 0
            while i < len(pairs) - 1:
                case_parts.append(f"WHEN {col} = {pairs[i]} THEN {pairs[i+1]}")
                i += 2
            
            # Last argument is default if odd number of remaining args
            if len(pairs) % 2 == 1:
                default = pairs[-1]
            else:
                default = "NULL"
            
            return f"CASE {' '.join(case_parts)} ELSE {default} END"
        
        result = re.sub(r"DECODE\s*\(([^)]+)\)", decode_to_case, sql, flags=re.IGNORECASE)
        
        if result != sql:
            notes.append("Converted DECODE to CASE WHEN")
        
        return result, notes
    
    def _parse_function_args(self, args_str: str) -> List[str]:
        """Parse function arguments handling nested parentheses."""
        args = []
        current = ""
        depth = 0
        
        for char in args_str:
            if char == '(':
                depth += 1
                current += char
            elif char == ')':
                depth -= 1
                current += char
            elif char == ',' and depth == 0:
                args.append(current.strip())
                current = ""
            else:
                current += char
        
        if current.strip():
            args.append(current.strip())
        
        return args
    
    def _convert_mysql_date_format(self, sql: str) -> Tuple[str, List[str]]:
        """Convert MySQL DATE_FORMAT to PostgreSQL TO_CHAR."""
        notes = []
        
        if "DATE_FORMAT" not in sql.upper():
            return sql, notes
        
        def convert_format(match):
            expr, fmt = match.group(1), match.group(2)
            # Convert MySQL format specifiers to PostgreSQL
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
            return f"TO_CHAR({expr}, '{pg_fmt}')"
        
        result = re.sub(
            r"DATE_FORMAT\s*\(([^,]+),\s*'([^']+)'\)",
            convert_format, sql, flags=re.IGNORECASE
        )
        
        if result != sql:
            notes.append("Converted DATE_FORMAT to TO_CHAR")
        
        return result, notes
    
    def _convert_postgres_to_char(self, sql: str) -> Tuple[str, List[str]]:
        """Convert PostgreSQL TO_CHAR to MySQL DATE_FORMAT."""
        notes = []
        
        if "TO_CHAR" not in sql.upper():
            return sql, notes
        
        def convert_format(match):
            expr, fmt = match.group(1), match.group(2)
            # Convert PostgreSQL format specifiers to MySQL
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
            return f"DATE_FORMAT({expr}, '{my_fmt}')"
        
        result = re.sub(
            r"TO_CHAR\s*\(([^,]+),\s*'([^']+)'\)",
            convert_format, sql, flags=re.IGNORECASE
        )
        
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
        
        # Add LIMIT if not already present
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
        
        # Remove ROWNUM condition
        result = re.sub(r"\s*AND\s+ROWNUM\s*<=?\s*\d+", "", result, flags=re.IGNORECASE)
        result = re.sub(r"\s*WHERE\s+ROWNUM\s*<=?\s*\d+", "", result, flags=re.IGNORECASE)
        
        # Add LIMIT if not already present
        if "LIMIT" not in result.upper():
            result = result.rstrip(';').rstrip() + f" LIMIT {n}"
        
        notes.append(f"Converted ROWNUM to LIMIT {n}")
        return result, notes
    
    def _fix_group_concat_default_separator(self, sql: str) -> Tuple[str, List[str]]:
        """Fix GROUP_CONCAT without separator for STRING_AGG conversion."""
        notes = []
        
        # Match GROUP_CONCAT without SEPARATOR clause
        pattern = r"GROUP_CONCAT\s*\((\w+)\)(?!\s+SEPARATOR)"
        
        def add_default_separator(match):
            col = match.group(1)
            return f"STRING_AGG({col}::TEXT, ',')"
        
        result = re.sub(pattern, add_default_separator, sql, flags=re.IGNORECASE)
        
        if result != sql:
            notes.append("Converted GROUP_CONCAT to STRING_AGG with default separator")
        
        return result, notes
    
    def _check_warnings(self, sql: str, source: str, target: str) -> List[str]:
        """Check for constructs that may need manual attention.
        
        Args:
            sql: Original SQL
            source: Source dialect
            target: Target dialect
            
        Returns:
            List of warning messages
        """
        warnings = []
        sql_upper = sql.upper()
        
        # Hive INSERT OVERWRITE
        if source == "hive" and "INSERT OVERWRITE" in sql_upper:
            if target in ("mysql", "postgres", "tsql", "oracle"):
                warnings.append(
                    f"WARNING: INSERT OVERWRITE not supported in {target}. "
                    "Use TRUNCATE + INSERT or MERGE instead."
                )
        
        # Oracle CONNECT BY
        if source == "oracle" and "CONNECT BY" in sql_upper:
            if target in ("hive", "postgres", "mysql"):
                warnings.append(
                    "WARNING: CONNECT BY requires manual conversion to WITH RECURSIVE CTE"
                )
        
        # Hive DISTRIBUTE BY / CLUSTER BY
        if source == "hive" and target in ("mysql", "postgres", "oracle", "tsql"):
            if "DISTRIBUTE BY" in sql_upper or "CLUSTER BY" in sql_upper:
                warnings.append(
                    "WARNING: DISTRIBUTE BY/CLUSTER BY are Hive-specific hints, removed in target"
                )
        
        # Stored procedures / PL/SQL
        if any(kw in sql_upper for kw in ["CREATE PROCEDURE", "CREATE FUNCTION", "BEGIN", "DECLARE"]):
            warnings.append(
                "WARNING: Procedural code detected. Stored procedure syntax varies significantly between databases."
            )
        
        # Materialized views
        if "MATERIALIZED VIEW" in sql_upper:
            warnings.append(
                "WARNING: Materialized view syntax and refresh mechanisms vary by database."
            )
        
        return warnings
    
    def get_stats(self) -> dict:
        """Get post-processor statistics.
        
        Returns:
            Dictionary with stats
        """
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
