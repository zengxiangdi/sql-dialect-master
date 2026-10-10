#!/usr/bin/env python3
"""Rule Engine for SQL dialect transformations.

Provides a declarative rule-based system for post-processing SQL transformations
that sqlglot doesn't handle natively.
"""
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Tuple

from .function_call_scanner import replace_function_calls
from .p1_sql_scanner import executable_segments, mask_non_executable, split_top_level_args

# Configure module logger
logger = logging.getLogger(__name__)


# Sentinel marker that the structured STRING_AGG rewriter appends to its
# output when the separator argument is a dynamic expression.  MySQL's
# GROUP_CONCAT grammar accepts only a plain string literal for
# ``SEPARATOR str_val`` — a dynamic expression there is not executable
# MySQL.  No semantics-preserving rewrite exists (a pre-computed
# constant would change per-row semantics; a GROUP_CONCAT-of-separators
# trick is undefined behavior).  The conversion must therefore fail
# closed: ``PostProcessor.process`` strips the marker and records the
# fail-closed note, so both entry points (``rule_engine.apply_rules``
# and ``SQLTranspiler.transpile``) surface the failure without carrying
# the marker into any returned SQL.
DYNAMIC_SEPARATOR_FAIL_NOTE = (
    "B2-1b fail-closed: STRING_AGG dynamic separator is not expressible as "
    "a MySQL GROUP_CONCAT SEPARATOR (string literal only); the conversion "
    "is not executable on the target and is reported as a failure."
)

# Internal sentinel token (B2-1c) appended to the rewriter's output for
# every dynamic-separator STRING_AGG call.  It is a 32-character
# high-entropy marker containing a NUL byte that cannot appear in valid
# SQL; it is NOT a SQL comment and carries no newline dependency, so
# surrounding text on the same line or subsequent lines is never
# consumed.  The rule engine strips every occurrence before returning
# SQL to any caller.
_DYNAMIC_SEPARATOR_SENTINEL = "\x00@@B2_1C_DYN_SEP@@\x00"


def strip_dynamic_separator_sentinel(sql: str) -> Tuple[str, bool]:
    """Remove every embedded dynamic-separator sentinel token from ``sql``.

    Returns ``(cleaned_sql, was_present)``.  The token is an exact
    substring removed in place; no line-boundary or regex assumption is
    made, so multi-line SQL, multiple dynamic calls in one statement,
    and trailing text on the call's own line are all preserved intact.
    """
    was_present = _DYNAMIC_SEPARATOR_SENTINEL in sql
    cleaned = sql.replace(_DYNAMIC_SEPARATOR_SENTINEL, "")
    return cleaned, was_present


def strip_dynamic_separator_marker(sql: str) -> Tuple[str, bool]:
    """Deprecated B2-1b alias; delegates to ``strip_dynamic_separator_sentinel``."""
    return strip_dynamic_separator_sentinel(sql)





def _is_plain_string_literal(text: str, source_dialect: str = "") -> bool:
    """True when text is a plain string literal in the given source dialect.

    Quote interpretation is dialect-aware:
    - PostgreSQL / Oracle / snowflake / redshift: double quotes mark
      IDENTIFIERS, so a double-quoted argument is never a string literal;
    - T-SQL / MySQL / duckdb / clickhouse / hive-family: double quotes
      mark string literals;
    - single quotes mark string literals in all source dialects.
    """
    text = text.strip()
    if len(text) < 2:
        return False
    quote = text[0]
    if quote == "'":
        # Single quotes mark string literals in every source dialect
        # (PostgreSQL, T-SQL, MySQL, Oracle, …).  A plain literal has
        # no UNESCAPED quote inside; a doubled ``''`` pair is the
        # source dialect's escape for a literal quote and does not end
        # the literal.
        inner = text[1:-1]
        i = 0
        while i < len(inner):
            if inner[i] != quote:
                i += 1
                continue
            if i + 1 < len(inner) and inner[i + 1] == quote:
                i += 2  # escaped quote, skip the pair
                continue
            return False  # unescaped closing quote too early
        return True
    # Double-quote interpretation is ambiguous without session state.
    # - PostgreSQL / Oracle / Snowflake / Redshift: double quotes mark
    #   identifiers (ANSI SQL), never string literals, unambiguously.
    # - T-SQL: the meaning of double quotes depends on the
    #   QUOTED_IDENTIFIER session setting.  QUOTED_IDENTIFIER ON
    #   (the default in SQL Server and the setting used by most
    #   clients) makes "foo" an identifier, not a string literal.
    #   The transpiler has no QUOTED_IDENTIFIER input; treating a
    #   double-quoted argument as a string literal when the session
    #   actually has QUOTED_IDENTIFIER ON would silently convert a
    #   source identifier into a target string constant.  The safe
    #   default is to fail closed (see B2-1d).
    # - MySQL / MariaDB: double quotes mark string literals by default
    #   (ANSI_QUOTES OFF is the default), so a double-quoted argument
    #   is unambiguously a string literal in those dialects.
    if quote != '"':
        return False
    if source_dialect in ("postgres", "oracle", "snowflake", "redshift", "tsql"):
        # Ambiguous or identifier-interpretation: never a plain string
        # literal without session state.
        return False
    inner = text[1:-1]
    i = 0
    while i < len(inner):
        if inner[i] != '"':
            i += 1
            continue
        if i + 1 < len(inner) and inner[i + 1] == '"':
            i += 2
            continue
        return False
    return True


def _requote_for_mysql(inner: str, original_quotes: str) -> str:
    """Convert a plain string literal's inner text to MySQL single-quoted form.

    ``original_quotes`` is the source dialect's quote style for the literal.
    When single-quoted, the inner text may use doubled ``''`` as the escape
    (PostgreSQL / T-SQL / MariaDB form); when double-quoted (T-SQL), the
    inner text may use doubled ``""`` as the escape.  Both doubled-pair
    escapes are unwound back to a plain quote, then re-escaped to MySQL's
    backslash-single-quote form.
    """
    if original_quotes == "'":
        inner = inner.replace("''", "'")
    else:
        inner = inner.replace('""', '"')
    inner = inner.replace("'", "\\'")
    return inner


def _replace_string_agg_to_group_concat(
    args: str, original: str, source_dialect: str = ""
) -> str:
    """Convert STRING_AGG to GROUP_CONCAT preserving nested expressions.

    - Fixed string-literal separators are re-quoted for GROUP_CONCAT's
      ``SEPARATOR str_val`` clause, with single-quote escaping preserved
      (a doubled ``\'\'`` inside a literal stays doubled).
    - Dynamic separator expressions (CONCAT(...), CASE ... END, ...)
      cannot be expressed in MySQL: ``SEPARATOR`` accepts only a string
      literal.  The rewriter fails closed with a marker comment instead
      of emitting unexecutable SQL and reporting success.
    - Double-quoted arguments are interpreted per source dialect (see
      _is_plain_string_literal); in PostgreSQL a double-quoted separator
      is an identifier, not a string, and is treated as dynamic (unsupported).
    """
    values = split_top_level_args(args)
    if len(values) != 2 or not all(values):
        return original
    expression, separator = values
    if _is_plain_string_literal(separator, source_dialect):
        # Fixed literal separator: normalize its inner text to MySQL
        # single-quoted form, preserving the content and escape semantics.
        separator = separator.strip()
        inner = separator[1:-1]
        mysql_literal = _requote_for_mysql(inner, separator[0])
        return f"GROUP_CONCAT({expression} SEPARATOR '{mysql_literal}')"
    # Dynamic separator: fail closed (B2-1b / B2-1c).  The original
    # call is preserved verbatim; the sentinel token is appended
    # directly after it.  The rule engine strips the token before
    # returning SQL to any caller and records DYNAMIC_SEPARATOR_FAIL_NOTE
    # in the notes.
    return original + _DYNAMIC_SEPARATOR_SENTINEL


def _replace_group_concat_to_string_agg(args: str, original: str) -> str:
    """Convert GROUP_CONCAT to STRING_AGG preserving DISTINCT, ORDER BY, SEPARATOR."""
    separator_position = _top_level_keyword(args, "SEPARATOR")
    before_separator = args if separator_position < 0 else args[:separator_position].rstrip()
    separator = "','" if separator_position < 0 else args[separator_position + len("SEPARATOR"):].strip()
    if not separator:
        return original

    order_position = _top_level_keyword(before_separator, "ORDER BY")
    expression = before_separator if order_position < 0 else before_separator[:order_position].rstrip()
    order_by = None if order_position < 0 else before_separator[order_position + len("ORDER BY"):].strip()
    distinct = bool(re.match(r"^DISTINCT\b", expression, re.IGNORECASE))
    if distinct:
        expression = re.sub(r"^DISTINCT\s+", "", expression, count=1, flags=re.IGNORECASE).strip()
    if not expression:
        return original

    prefix = "DISTINCT " if distinct else ""
    result = f"STRING_AGG({prefix}{expression}::TEXT, {separator}"
    if order_by:
        result += f" ORDER BY {order_by}"
    return result + ")"


def _top_level_keyword(text: str, keyword: str) -> int:
    """Return the position of a keyword at top-level parentheses depth, or -1."""
    masked = mask_non_executable(text)
    wanted = keyword.upper()
    depth = 0
    for index, char in enumerate(masked):
        if char == "(":
            depth += 1
            continue
        if char == ")" and depth:
            depth -= 1
            continue
        if depth == 0 and masked[index:index + len(wanted)].upper() == wanted:
            before = masked[index - 1] if index else " "
            after_index = index + len(wanted)
            after = masked[after_index] if after_index < len(masked) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return index
    return -1


def _replace_listagg_to_collect_list_wrapper(sql: str, _original_call: str = "") -> str:
    """Wrapper for LISTAGG conversion that works with the structured replacer interface.

    NOTE: This wrapper is intentionally a no-op. The LISTAGG conversion is handled
    by the full_sql_rewriter (_replace_listagg_to_collect_list) which operates on
    the full SQL before sqlglot processes it. By the time this wrapper would be
    called, the rule engine has already run and sqlglot may have transformed
    LISTAGG into another function (e.g., GROUP_CONCAT for oracle→hive).
    """
    return sql


def _replace_listagg_to_collect_list(sql: str) -> tuple[str, bool]:
    """Convert Oracle LISTAGG to Hive ARRAY_JOIN(COLLECT_LIST(...))."""
    function_name = "LISTAGG"
    masked = mask_non_executable(sql)
    name_upper = function_name.upper()
    length = len(sql)
    result: list[str] = []
    cursor = 0
    index = 0
    applied = False

    while index < length:
        if masked[index:index + len(function_name)].upper() != name_upper:
            index += 1
            continue
        if index > 0 and (masked[index - 1].isalnum() or masked[index - 1] == "_"):
            index += 1
            continue

        open_index = index + len(function_name)
        while open_index < length and masked[open_index].isspace():
            open_index += 1
        if open_index >= length or masked[open_index] != "(":
            index += 1
            continue

        depth = 0
        close_index = open_index
        while close_index < length:
            char = masked[close_index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            close_index += 1
        if close_index >= length or depth != 0:
            index += 1
            continue

        suffix_index = close_index + 1
        while suffix_index < length and masked[suffix_index].isspace():
            suffix_index += 1
        within_group = "WITHIN" + " " + "GROUP"
        if masked[suffix_index:suffix_index + len(within_group)].upper() != within_group:
            index += 1
            continue
        suffix_index += len(within_group)
        while suffix_index < length and masked[suffix_index].isspace():
            suffix_index += 1
        if suffix_index >= length or masked[suffix_index] != "(":
            index += 1
            continue

        order_depth = 0
        order_close = suffix_index
        while order_close < length:
            char = masked[order_close]
            if char == "(":
                order_depth += 1
            elif char == ")":
                order_depth -= 1
                if order_depth == 0:
                    break
            order_close += 1
        if order_close >= length or order_depth != 0:
            index += 1
            continue

        args = sql[open_index + 1:close_index]
        order_clause = sql[suffix_index + 1:order_close].strip()
        if not re.match(r"^ORDER\s+BY\b", order_clause, re.IGNORECASE):
            index += 1
            continue

        values = split_top_level_args(args)
        if len(values) != 2 or not all(values):
            index += 1
            continue

        result.append(sql[cursor:index])
        result.append(f"ARRAY_JOIN(COLLECT_LIST({values[0]}), {values[1]})")
        cursor = order_close + 1
        index = cursor
        applied = True

    if not applied:
        return sql, False
    result.append(sql[cursor:])
    return "".join(result), True


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


class RuleSafety(Enum):
    """Safety classification for transformation rules."""
    STRUCTURED = "structured"           # scanner-backed function rewrites
    BOUNDED_REGEX = "bounded_regex"      # regex with explicit lexical boundaries
    LEGACY_REGEX = "legacy_regex"        # plain regex, potentially unsafe


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
        function_name: Optional function name for scanner-backed structural rewrites
        structured_replacement: Optional argument-aware replacement template
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
    function_name: str | None = None
    structured_replacement: str | None = None
    # Custom callable replacer for complex structured rewrites that can't
    # be expressed as a simple format string. Receives (args_str, original_call)
    # and returns the replacement string.
    structured_replacer: Callable[[str, str], str] | None = None
    # For rules that need the full SQL context (e.g., LISTAGG with WITHIN GROUP).
    # Receives (sql,) and returns (transformed_sql, applied_bool).
    full_sql_rewriter: Callable[[str], tuple[str, bool]] | None = None

    @property
    def safety(self) -> RuleSafety:
        """Return the safety classification for this rule."""
        if self.function_name and self.structured_replacement:
            return RuleSafety.STRUCTURED
        # Bounded regex rules use word boundaries and explicit patterns
        if self.pattern and (self.pattern.startswith(r"\b") or
                             self.pattern.startswith(r"(?<!)") or
                             "WITHIN GROUP" in self.pattern.upper() or
                             "LATERAL" in self.pattern.upper()):
            return RuleSafety.BOUNDED_REGEX
        return RuleSafety.LEGACY_REGEX

    def matches_dialects(self, source: str, target: str) -> bool:
        """Check if this rule applies to the given dialect pair."""
        source_values = {value.strip().lower() for value in self.source.split(",")}
        target_values = {value.strip().lower() for value in self.target.split(",")}
        source_match = "*" in source_values or source.lower() in source_values
        target_match = "*" in target_values or target.lower() in target_values
        return source_match and target_match

    def _apply_structured(
        self, sql: str, source_dialect: str = ""
    ) -> Tuple[str, bool]:
        """Apply an explicitly scanner-backed function rewrite.

        ``source_dialect`` (lower-cased) is threaded to
        ``structured_replacer`` callables that need dialect-aware parsing
        of argument text (e.g. STRING_AGG separator quote interpretation
        differs between PostgreSQL — where ``"x"`` is an identifier — and
        T-SQL, where it is a string literal).
        """
        if not self.function_name:
            return sql, False

        # If a full-SQL rewriter is provided, use it directly.
        if self.full_sql_rewriter is not None:
            return self.full_sql_rewriter(sql)

        applied = False

        def replacer(args: str, original_call: str) -> str:
            nonlocal applied
            if self.structured_replacer is not None:
                try:
                    transformed = self.structured_replacer(
                        args, original_call, source_dialect
                    )
                except TypeError:
                    transformed = self.structured_replacer(args, original_call)
                applied = applied or transformed != original_call
                return transformed
            values = split_top_level_args(args)
            expected = self.structured_replacement.count("{")
            if len(values) != expected:
                return original_call
            applied = True
            return self.structured_replacement.format(*values)

        transformed = replace_function_calls(sql, self.function_name, replacer)
        return transformed, applied

    def apply(
        self, sql: str, source_dialect: str = ""
    ) -> Tuple[str, bool]:
        """Apply this rule only to executable SQL segments."""
        if not self.enabled:
            return sql, False

        if self.function_name and (self.structured_replacement or self.structured_replacer or self.full_sql_rewriter):
            return self._apply_structured(sql, source_dialect)

        pattern = getattr(self, "_compiled_pattern", None)
        if pattern is None:
            pattern = re.compile(self.pattern, re.IGNORECASE)
            self._compiled_pattern = pattern

        parts = []
        cursor = 0
        applied = False
        for start, end in executable_segments(sql):
            parts.append(sql[cursor:start])
            segment = sql[start:end]
            transformed, count = pattern.subn(self.replacement, segment)
            parts.append(transformed)
            applied = applied or count > 0
            cursor = end

        parts.append(sql[cursor:])
        return "".join(parts), applied


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
        priority=70,
        function_name="COLLECT_LIST",
        structured_replacement="ARRAY_AGG({0})",
    ),
    TransformRule(
        name="postgres_array_agg_to_hive",
        source="postgres",
        target="hive,spark",
        pattern=r'ARRAY_AGG\s*\(([^)]+)\)',
        replacement=r'COLLECT_LIST(\1)',
        note="Converted ARRAY_AGG to COLLECT_LIST",
        category=RuleCategory.ARRAY,
        priority=70,
        function_name="ARRAY_AGG",
        structured_replacement="COLLECT_LIST({0})",
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
        priority=80,
        function_name="LISTAGG",
        full_sql_rewriter=_replace_listagg_to_collect_list,
    ),
    TransformRule(
        name="tsql_string_agg_to_mysql",
        source="tsql",
        target="mysql",
        pattern=r"STRING_AGG\s*\((\w+)\s*,\s*'([^']+)'\)",
        replacement=r"GROUP_CONCAT(\1 SEPARATOR '\2')",
        note="Converted STRING_AGG to GROUP_CONCAT",
        category=RuleCategory.AGGREGATION,
        priority=70,
        function_name="STRING_AGG",
        structured_replacer=_replace_string_agg_to_group_concat,
    ),
    TransformRule(
        name="mysql_group_concat_to_postgres",
        source="mysql",
        target="postgres",
        pattern=r"GROUP_CONCAT\s*\((\w+)(?:\s+SEPARATOR\s+'([^']+)')?\)",
        replacement=r"STRING_AGG(\1::TEXT, '\2')",
        note="Converted GROUP_CONCAT to STRING_AGG",
        category=RuleCategory.AGGREGATION,
        priority=70,
        function_name="GROUP_CONCAT",
        structured_replacer=_replace_group_concat_to_string_agg,
    ),
    TransformRule(
        name="postgres_string_agg_to_mysql",
        source="postgres",
        target="mysql",
        pattern=r"STRING_AGG\s*\(([^,]+),\s*'([^']+)'\)",
        replacement=r"GROUP_CONCAT(\1 SEPARATOR '\2')",
        note="Converted STRING_AGG to GROUP_CONCAT",
        category=RuleCategory.AGGREGATION,
        priority=70,
        function_name="STRING_AGG",
        structured_replacer=_replace_string_agg_to_group_concat,
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
        priority=60,
        function_name="IFNULL",
        structured_replacement="COALESCE({0}, {1})",
    ),
    TransformRule(
        name="oracle_nvl_to_coalesce",
        source="oracle",
        target="mysql,postgres,hive,spark,tsql,trino,snowflake",
        pattern=r"\bNVL\s*\(([^,]+),\s*([^)]+)\)",
        replacement=r"COALESCE(\1, \2)",
        note="Converted NVL to COALESCE",
        category=RuleCategory.NULL_HANDLING,
        priority=60,
        function_name="NVL",
        structured_replacement="COALESCE({0}, {1})",
    ),
    TransformRule(
        name="tsql_isnull_to_coalesce",
        source="tsql",
        target="mysql,postgres,hive,oracle,spark,trino,snowflake",
        pattern=r"\bISNULL\s*\(([^,]+),\s*([^)]+)\)",
        replacement=r"COALESCE(\1, \2)",
        note="Converted ISNULL to COALESCE",
        category=RuleCategory.NULL_HANDLING,
        priority=60,
        function_name="ISNULL",
        structured_replacement="COALESCE({0}, {1})",
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

    def apply_rules(
        self,
        sql: str,
        source: str,
        target: str,
    ) -> Tuple[str, List[str]]:
        """Apply all matching rules to SQL.

        Args:
            sql: SQL to transform
            source: Source dialect
            target: Target dialect

        Returns:
            Tuple of (transformed_sql, list_of_notes).  Fixed-literal
            STRING_AGG separators convert to a valid MySQL
            ``GROUP_CONCAT(... SEPARATOR '...')``.  When a separator is
            a dynamic expression the rewriter fails closed: the original
            call is left untouched, the marker is stripped from the
            returned SQL, and ``DYNAMIC_SEPARATOR_FAIL_NOTE`` is appended
            to the notes — callers must treat that note as "conversion
            did not complete for this construct" and must not report
            the overall conversion as successful.
        """
        result = sql
        notes = []
        source_lower = source.lower()
        fail_closed_dynamic_separator = False

        for rule in self.rules:
            if rule.matches_dialects(source, target):
                new_result, applied = rule.apply(result, source_lower)
                if applied:
                    cleaned, sentinel_was_present = strip_dynamic_separator_sentinel(new_result)
                    if sentinel_was_present:
                        fail_closed_dynamic_separator = True
                        # B2-1d: do NOT report the rule's success note
                        # when the rewrite actually failed closed; the
                        # success note would contradict the fail-closed
                        # result.  The DYNAMIC_SEPARATOR_FAIL_NOTE
                        # (appended below) is the only note for this
                        # rule in that case.
                    else:
                        result = cleaned
                        notes.append(rule.note)
                    if sentinel_was_present:
                        result = cleaned

        if fail_closed_dynamic_separator:
            notes.append(DYNAMIC_SEPARATOR_FAIL_NOTE)

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
