#!/usr/bin/env python3
"""Rule Engine for SQL dialect transformations.

Provides a declarative rule-based system for post-processing SQL transformations
that sqlglot doesn't handle natively.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Callable, Tuple
from enum import Enum

# Configure module logger
logger = logging.getLogger(__name__)


class RuleCategory(Enum):
    """Categories of transformation rules."""
    FUNCTION = "function"
    SYNTAX = "syntax"
    TYPE = "type"
    AGGREGATION = "aggregation"
    DATE_TIME = "date_time"
    JSON = "json"
    ARRAY = "array"
    LIMIT = "limit"
    NULL_HANDLING = "null_handling"


@dataclass
class TransformRule:
    """A single transformation rule.
    
    Attributes:
        name: Unique rule identifier
        source: Source dialect(s) - can be "*" for any
        target: Target dialect(s) - can be "*" for any
        pattern: Regex pattern to match
        replacement: Replacement string or callable
        note: Human-readable description of the transformation
        category: Rule category for organization
        priority: Higher priority rules are applied first (default 50)
        enabled: Whether the rule is active
    """
    name: str
    source: str  # Can be "hive", "mysql,oracle", or "*"
    target: str  # Can be "postgres", "mysql,hive", or "*"
    pattern: str
    replacement: str  # Can contain \1, \2 for groups
    note: str
    category: RuleCategory = RuleCategory.FUNCTION
    priority: int = 50
    enabled: bool = True
    
    def matches_dialects(self, source: str, target: str) -> bool:
        """Check if this rule applies to the given dialect pair."""
        source_values = {value.strip().lower() for value in self.source.split(",")}
        target_values = {value.strip().lower() for value in self.target.split(",")}
        source_match = "*" in source_values or source.lower() in source_values
        target_match = "*" in target_values or target.lower() in target_values
        return source_match and target_match
    
    def apply(self, sql: str) -> Tuple[str, bool]:
        """Apply this rule to SQL.
        
        Returns:
            Tuple of (transformed_sql, was_applied)
        """
        if not self.enabled:
            return sql, False
        
        pattern = getattr(self, "_compiled_pattern", None)
        if pattern is None:
            pattern = re.compile(self.pattern, re.IGNORECASE)
            self._compiled_pattern = pattern
        new_sql, count = pattern.subn(self.replacement, sql)
        return new_sql, count > 0


# =============================================================================
# Rule Definitions - Organized by Category
# =============================================================================

TRANSFORM_RULES: List[TransformRule] = [
    # =========================================================================
    # ARRAY/EXPLODE Rules
    # =========================================================================
    TransformRule(
        name="hive_explode_to_postgres_unnest",
        source="hive,spark",
        target="postgres",
        pattern=r'LATERAL\s+VIEW\s+EXPLODE\s*\((\w+)\)\s+(\w+)\s+AS\s+(\w+)',
        replacement=r'CROSS JOIN LATERAL UNNEST(\1) WITH ORDINALITY AS \2(\3, idx)',
        note="Converted LATERAL VIEW EXPLODE to UNNEST WITH ORDINALITY",
        category=RuleCategory.ARRAY,
        priority=80
    ),
    TransformRule(
        name="hive_collect_list_to_postgres",
        source="hive,spark",
        target="postgres",
        pattern=r'COLLECT_LIST\s*\(([^)]+)\)',
        replacement=r'ARRAY_AGG(\1)',
        note="Converted COLLECT_LIST to ARRAY_AGG",
        category=RuleCategory.ARRAY,
        priority=70
    ),
    TransformRule(
        name="postgres_array_agg_to_hive",
        source="postgres",
        target="hive,spark",
        pattern=r'ARRAY_AGG\s*\(([^)]+)\)',
        replacement=r'COLLECT_LIST(\1)',
        note="Converted ARRAY_AGG to COLLECT_LIST",
        category=RuleCategory.ARRAY,
        priority=70
    ),
    TransformRule(
        name="snowflake_flatten_to_hive",
        source="snowflake",
        target="hive,spark",
        pattern=r'LATERAL\s+FLATTEN\s*\(\s*INPUT\s*=>\s*(\w+)\s*\)\s+(\w+)',
        replacement=r'LATERAL VIEW EXPLODE(\1) \2 AS value',
        note="Converted FLATTEN to LATERAL VIEW EXPLODE",
        category=RuleCategory.ARRAY,
        priority=80
    ),
    TransformRule(
        name="snowflake_flatten_to_postgres",
        source="snowflake",
        target="postgres",
        pattern=r'LATERAL\s+FLATTEN\s*\(\s*INPUT\s*=>\s*(\w+)\s*\)\s+(\w+)',
        replacement=r'CROSS JOIN LATERAL UNNEST(\1) AS \2(value)',
        note="Converted FLATTEN to UNNEST",
        category=RuleCategory.ARRAY,
        priority=80
    ),
    TransformRule(
        name="clickhouse_array_join_to_postgres",
        source="clickhouse",
        target="postgres",
        pattern=r'ARRAY\s+JOIN\s+(\w+)(?:\s+AS\s+(\w+))?',
        replacement=r'CROSS JOIN LATERAL UNNEST(\1) AS t(value)',
        note="Converted ARRAY JOIN to UNNEST",
        category=RuleCategory.ARRAY,
        priority=80
    ),
    TransformRule(
        name="hive_size_to_postgres",
        source="hive,spark",
        target="postgres",
        pattern=r'\bSIZE\s*\((\w+)\)',
        replacement=r'ARRAY_LENGTH(\1, 1)',
        note="Converted SIZE to ARRAY_LENGTH",
        category=RuleCategory.ARRAY,
        priority=60
    ),
    TransformRule(
        name="postgres_array_length_to_hive",
        source="postgres",
        target="hive,spark",
        pattern=r'ARRAY_LENGTH\s*\((\w+),\s*\d+\)',
        replacement=r'SIZE(\1)',
        note="Converted ARRAY_LENGTH to SIZE",
        category=RuleCategory.ARRAY,
        priority=60
    ),
    TransformRule(
        name="duckdb_list_to_hive",
        source="duckdb",
        target="hive,spark",
        pattern=r'\bLIST\b',
        replacement=r'ARRAY',
        note="Converted LIST to ARRAY",
        category=RuleCategory.ARRAY,
        priority=50
    ),
    
    # =========================================================================
    # AGGREGATION Rules
    # =========================================================================
    TransformRule(
        name="oracle_listagg_to_hive",
        source="oracle",
        target="hive,spark",
        pattern=r"LISTAGG\s*\((\w+)\s*,\s*'([^']+)'\)\s*WITHIN\s+GROUP\s*\(\s*ORDER\s+BY\s+([^)]+)\)",
        replacement=r"ARRAY_JOIN(COLLECT_LIST(\1), '\2')",
        note="Converted LISTAGG to ARRAY_JOIN(COLLECT_LIST()). ORDER BY not preserved",
        category=RuleCategory.AGGREGATION,
        priority=80
    ),
    TransformRule(
        name="tsql_string_agg_to_mysql",
        source="tsql",
        target="mysql",
        pattern=r"STRING_AGG\s*\((\w+)\s*,\s*'([^']+)'\)",
        replacement=r"GROUP_CONCAT(\1 SEPARATOR '\2')",
        note="Converted STRING_AGG to GROUP_CONCAT",
        category=RuleCategory.AGGREGATION,
        priority=70
    ),
    TransformRule(
        name="mysql_group_concat_to_postgres",
        source="mysql",
        target="postgres",
        pattern=r"GROUP_CONCAT\s*\((\w+)(?:\s+SEPARATOR\s+'([^']+)')?\)",
        replacement=r"STRING_AGG(\1::TEXT, '\2')",
        note="Converted GROUP_CONCAT to STRING_AGG",
        category=RuleCategory.AGGREGATION,
        priority=70
    ),
    TransformRule(
        name="postgres_string_agg_to_mysql",
        source="postgres",
        target="mysql",
        pattern=r"STRING_AGG\s*\(([^,]+),\s*'([^']+)'\)",
        replacement=r"GROUP_CONCAT(\1 SEPARATOR '\2')",
        note="Converted STRING_AGG to GROUP_CONCAT",
        category=RuleCategory.AGGREGATION,
        priority=70
    ),
    TransformRule(
        name="clickhouse_group_array_to_postgres",
        source="clickhouse",
        target="postgres",
        pattern=r'groupArray\s*\(([^)]+)\)',
        replacement=r'ARRAY_AGG(\1)',
        note="Converted groupArray to ARRAY_AGG",
        category=RuleCategory.AGGREGATION,
        priority=60
    ),
    
    # =========================================================================
    # NULL HANDLING Rules
    # =========================================================================
    TransformRule(
        name="mysql_ifnull_to_coalesce",
        source="mysql",
        target="postgres,oracle,hive,spark,trino,snowflake",
        pattern=r"IFNULL\s*\(([^,]+),\s*([^)]+)\)",
        replacement=r"COALESCE(\1, \2)",
        note="Converted IFNULL to COALESCE",
        category=RuleCategory.NULL_HANDLING,
        priority=60
    ),
    TransformRule(
        name="oracle_nvl_to_coalesce",
        source="oracle",
        target="mysql,postgres,hive,spark,tsql,trino,snowflake",
        pattern=r"\bNVL\s*\(([^,]+),\s*([^)]+)\)",
        replacement=r"COALESCE(\1, \2)",
        note="Converted NVL to COALESCE",
        category=RuleCategory.NULL_HANDLING,
        priority=60
    ),
    TransformRule(
        name="tsql_isnull_to_coalesce",
        source="tsql",
        target="mysql,postgres,hive,oracle,spark,trino,snowflake",
        pattern=r"\bISNULL\s*\(([^,]+),\s*([^)]+)\)",
        replacement=r"COALESCE(\1, \2)",
        note="Converted ISNULL to COALESCE",
        category=RuleCategory.NULL_HANDLING,
        priority=60
    ),
    
    # =========================================================================
    # DATE/TIME Rules
    # =========================================================================
    TransformRule(
        name="tsql_getdate_to_mysql",
        source="tsql",
        target="mysql",
        pattern=r"GETDATE\s*\(\)",
        replacement=r"NOW()",
        note="Converted GETDATE to NOW",
        category=RuleCategory.DATE_TIME,
        priority=50
    ),
    TransformRule(
        name="tsql_getdate_to_postgres",
        source="tsql,redshift",
        target="postgres",
        pattern=r"GETDATE\s*\(\)",
        replacement=r"CURRENT_TIMESTAMP",
        note="Converted GETDATE to CURRENT_TIMESTAMP",
        category=RuleCategory.DATE_TIME,
        priority=50
    ),
    TransformRule(
        name="oracle_sysdate_to_postgres",
        source="oracle",
        target="postgres",
        pattern=r"\bSYSDATE\b",
        replacement=r"CURRENT_TIMESTAMP",
        note="Converted SYSDATE to CURRENT_TIMESTAMP",
        category=RuleCategory.DATE_TIME,
        priority=50
    ),
    TransformRule(
        name="mysql_now_to_oracle",
        source="mysql",
        target="oracle",
        pattern=r"NOW\s*\(\)",
        replacement=r"SYSDATE",
        note="Converted NOW to SYSDATE",
        category=RuleCategory.DATE_TIME,
        priority=50
    ),
    TransformRule(
        name="hive_unix_timestamp_to_postgres",
        source="hive,spark",
        target="postgres",
        pattern=r"UNIX_TIMESTAMP\s*\(\)",
        replacement=r"EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)::BIGINT",
        note="Converted UNIX_TIMESTAMP to EXTRACT(EPOCH)",
        category=RuleCategory.DATE_TIME,
        priority=60
    ),
    
    # =========================================================================
    # LIMIT/TOP Rules
    # =========================================================================
    TransformRule(
        name="mysql_limit_offset_to_postgres",
        source="mysql",
        target="postgres",
        pattern=r"LIMIT\s+(\d+)\s*,\s*(\d+)",
        replacement=r"LIMIT \2 OFFSET \1",
        note="Converted MySQL LIMIT offset,count to PostgreSQL LIMIT...OFFSET",
        category=RuleCategory.LIMIT,
        priority=70
    ),
    
    # =========================================================================
    # JSON Rules
    # =========================================================================
    TransformRule(
        name="mysql_json_extract_to_postgres",
        source="mysql",
        target="postgres",
        pattern=r"JSON_EXTRACT\s*\((\w+),\s*'\$\.(\w+)'\)",
        replacement=r"\1->>'\2'",
        note="Converted JSON_EXTRACT to ->> operator",
        category=RuleCategory.JSON,
        priority=60
    ),
    TransformRule(
        name="snowflake_parse_json_to_postgres",
        source="snowflake",
        target="postgres",
        pattern=r"PARSE_JSON\s*\(([^)]+)\)",
        replacement=r"\1::JSONB",
        note="Converted PARSE_JSON to ::JSONB cast",
        category=RuleCategory.JSON,
        priority=60
    ),
    
    # =========================================================================
    # STRING Rules
    # =========================================================================
    TransformRule(
        name="oracle_substr_to_mysql",
        source="oracle",
        target="mysql",
        pattern=r"\bSUBSTR\s*\(",
        replacement=r"SUBSTRING(",
        note="Converted SUBSTR to SUBSTRING",
        category=RuleCategory.FUNCTION,
        priority=40
    ),
    TransformRule(
        name="mysql_substring_to_oracle",
        source="mysql",
        target="oracle",
        pattern=r"\bSUBSTRING\s*\(",
        replacement=r"SUBSTR(",
        note="Converted SUBSTRING to SUBSTR",
        category=RuleCategory.FUNCTION,
        priority=40
    ),
    
    # =========================================================================
    # TYPE Rules
    # =========================================================================
    TransformRule(
        name="trino_row_to_hive",
        source="trino",
        target="hive,spark",
        pattern=r"\bROW\s*\(",
        replacement=r"STRUCT(",
        note="Converted ROW to STRUCT",
        category=RuleCategory.TYPE,
        priority=50
    ),
    TransformRule(
        name="hive_struct_to_trino",
        source="hive,spark",
        target="trino",
        pattern=r"\bSTRUCT\s*\(",
        replacement=r"ROW(",
        note="Converted STRUCT to ROW",
        category=RuleCategory.TYPE,
        priority=50
    ),
]


class RuleEngine:
    """Engine for applying transformation rules."""
    
    def __init__(self, rules: List[TransformRule] = None):
        """Initialize with rules.
        
        Args:
            rules: List of transformation rules. Uses default rules if None.
        """
        self.rules = list(TRANSFORM_RULES if rules is None else rules)
        self._sort_rules()
        self._compile_patterns()
    
    def apply_rules(self, sql: str, source: str, target: str) -> Tuple[str, List[str]]:
        """Apply all matching rules to SQL.
        
        Args:
            sql: SQL to transform
            source: Source dialect
            target: Target dialect
            
        Returns:
            Tuple of (transformed_sql, list_of_notes)
        """
        result = sql
        notes = []
        
        for rule in self.rules:
            if rule.matches_dialects(source, target):
                new_result, applied = rule.apply(result)
                if applied:
                    result = new_result
                    notes.append(rule.note)
        
        return result, notes
    
    def get_applicable_rules(self, source: str, target: str) -> List[TransformRule]:
        """Get all rules that apply to a dialect pair.
        
        Args:
            source: Source dialect
            target: Target dialect
            
        Returns:
            List of applicable rules
        """
        return [r for r in self.rules if r.matches_dialects(source, target)]
    
    def add_rule(self, rule: TransformRule) -> None:
        """Add a new rule.
        
        Args:
            rule: Rule to add
        
        Raises:
            ValueError: If a rule with the same name already exists.
            re.error: If the rule pattern is invalid.
        """
        if any(existing.name == rule.name for existing in self.rules):
            raise ValueError(f"Rule name already exists: {rule.name}")
        try:
            rule._compiled_pattern = re.compile(rule.pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid pattern in rule {rule.name}: {exc}") from exc
        self.rules.append(rule)
        self._sort_rules()
    
    def disable_rule(self, name: str) -> bool:
        """Disable a rule by name.
        
        Args:
            name: Rule name to disable
            
        Returns:
            True if rule was found and disabled
        """
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = False
                return True
        return False
    
    def enable_rule(self, name: str) -> bool:
        """Enable a rule by name.
        
        Args:
            name: Rule name to enable
            
        Returns:
            True if rule was found and enabled
        """
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = True
                return True
        return False
    
    def _sort_rules(self) -> None:
        """Sort rules deterministically: priority first, name as tie-breaker."""
        self.rules.sort(key=lambda rule: (-rule.priority, rule.name))
    
    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for better performance."""
        for rule in self.rules:
            if not hasattr(rule, '_compiled_pattern'):
                try:
                    rule._compiled_pattern = re.compile(rule.pattern, re.IGNORECASE)
                except re.error as e:
                    logger.warning(f"Failed to compile pattern for rule {rule.name}: {e}")
                    rule._compiled_pattern = None
    
    def validate_rules(self) -> List[str]:
        """Validate rules for common conflicts and invalid configurations.
        
        Returns:
            List of warning messages. Empty list means no issues found.
        """
        warnings = []
        names = set()
        
        for rule in self.rules:
            if rule.name in names:
                warnings.append(f"Duplicate rule name: {rule.name}")
            names.add(rule.name)
            
            if not rule.pattern:
                warnings.append(f"Empty pattern in rule: {rule.name}")
            
            # Check for potentially conflicting rules with same dialect/category
            # Calculate intersection rather than requiring exact selector equality.
            for other in self.rules:
                if rule.name >= other.name:
                    continue
                if (rule.category == other.category and 
                    rule.priority == other.priority and
                    self._dialect_sets_intersect(rule.source, other.source) and
                    self._dialect_sets_intersect(rule.target, other.target)):
                    warnings.append(
                        f"Potential conflict: {rule.name} and {other.name} "
                        f"have same priority/category and overlapping dialects"
                    )
        
        return warnings
    
    @staticmethod
    def _dialect_sets_intersect(first: str, second: str) -> bool:
        """Return whether two comma-separated dialect selectors overlap."""
        first_values = {value.strip().lower() for value in first.split(",")}
        second_values = {value.strip().lower() for value in second.split(",")}
        return "*" in first_values or "*" in second_values or bool(first_values & second_values)
    
    def get_stats(self) -> dict:
        """Get rule engine statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            "total_rules": len(self.rules),
            "enabled_rules": sum(1 for r in self.rules if r.enabled),
            "categories": {
                cat.value: sum(1 for r in self.rules if r.category == cat)
                for cat in RuleCategory
            },
            "average_priority": sum(r.priority for r in self.rules) / len(self.rules) if self.rules else 0,
        }


# Global rule engine instance
rule_engine = RuleEngine()
