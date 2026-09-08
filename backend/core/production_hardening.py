"""Second-pass production hardening helpers."""

import re

from .config import settings
from .nl2sql import NL2SQLGenerator, NL2SQLResult
from .parser import SQLParser, ParseResult
from .post_processor import PostProcessor
from .transpiler import SQLTranspiler


PARSER_MAX_INPUT_LENGTH = getattr(settings, "parser_max_sql_length", settings.transpiler_max_sql_length)
NL2SQL_MAX_INPUT_LENGTH = getattr(settings, "nl2sql_max_input_length", 8192)

_original_parser_parse = SQLParser.parse
_original_nl2sql_generate = NL2SQLGenerator.generate
_original_extract_conditions = NL2SQLGenerator._extract_conditions_enhanced


def _parse_with_length_guard(self: SQLParser, sql: str) -> ParseResult:
    """Reject oversized parser input before invoking sqlglot."""
    if not isinstance(sql, str):
        return ParseResult(success=False, error="SQL statement must be a string", dialect=self.dialect)
    if len(sql) > PARSER_MAX_INPUT_LENGTH:
        return ParseResult(
            success=False,
            error=f"SQL exceeds maximum length of {PARSER_MAX_INPUT_LENGTH} characters",
            dialect=self.dialect,
        )
    return _original_parser_parse(self, sql)


def _extract_conditions_with_explicit_english_comparisons(self, text: str, original: str):
    """Keep every explicit English comparison tied to its own column/value pair."""
    conditions = _original_extract_conditions(self, text, original)
    pattern = re.compile(
        r"\b(price|quantity|amount|age|score|rating|views|clicks)\s+"
        r"(greater\s+than\s+or\s+equal\s+to|less\s+than\s+or\s+equal\s+to|"
        r"greater\s+than|less\s+than|more\s+than|less|greater|above|below|under|over)\s+"
        r"(\d+\.?\d*)",
        re.IGNORECASE,
    )
    explicit = []
    for match in pattern.finditer(text):
        column = match.group(1).lower()
        phrase = re.sub(r"\s+", " ", match.group(2).strip().lower())
        value = match.group(3)
        if "greater than or equal" in phrase:
            operator = ">="
        elif "less than or equal" in phrase:
            operator = "<="
        elif phrase.startswith(("greater", "more", "above", "over")):
            operator = ">"
        else:
            operator = "<"
        explicit.append(f"{column} {operator} {value}")

    if not explicit:
        return conditions

    explicit_set = set(explicit)
    numeric_comparison = re.compile(
        r"^(price|quantity|amount|age|score|rating|views|clicks)\s+(>=|<=|!=|=|>|<)\s+\d+(?:\.\d*)?$"
    )
    filtered = [
        condition for condition in conditions
        if not numeric_comparison.fullmatch(condition) or condition in explicit_set
    ]
    for condition in explicit:
        if condition not in filtered:
            filtered.append(condition)
    return filtered


def _generate_with_length_guard(
    self: NL2SQLGenerator,
    text: str,
    dialect: str = None,
    table_hint: str = None,
    column_hints=None,
) -> NL2SQLResult:
    """Reject oversized NL2SQL input before tokenization and regex processing."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if len(text) > NL2SQL_MAX_INPUT_LENGTH:
        return NL2SQLResult(
            success=False,
            input_text=text[:200] + "...",
            dialect=dialect or self.default_dialect,
            explanation=f"Input text exceeds maximum length of {NL2SQL_MAX_INPUT_LENGTH} characters",
            suggestions=["Please shorten the natural-language query and try again."],
        )
    return _original_nl2sql_generate(self, text, dialect, table_hint, column_hints)


def _validate_output_strict(self: SQLTranspiler, sql: str, dialect: str):
    """Validate output under the requested target dialect with one known parser limitation."""
    try:
        import sqlglot
        sqlglot.parse_one(sql, read=dialect)
        return None
    except Exception as exc:
        message = str(exc)
        if (
            "Required keyword: 'unit' missing" in message
            and "TimestampTrunc" in message
            and dialect == "hive"
        ):
            return None
        return f"⚠️ Output SQL may have syntax issues: {dialect} dialect validation failed: {message[:160]}"


# The audit layer experimented with a replacement wrapper around the legacy
# function-call helper. Its call contract is relied on by DECODE/DATE_FORMAT/
# GROUP_CONCAT, so restore the exact helper while keeping quote-aware rule
# replacement and security scanning in audit_hardening._replace_outside.
try:
    from . import audit_hardening as _audit_hardening
    PostProcessor._replace_function_calls = _audit_hardening._ORIGINAL_REPLACE_FUNCTION_CALLS
except (AttributeError, ImportError):
    pass


SQLParser.parse = _parse_with_length_guard
NL2SQLGenerator._extract_conditions_enhanced = _extract_conditions_with_explicit_english_comparisons
NL2SQLGenerator.generate = _generate_with_length_guard
SQLTranspiler._validate_output = _validate_output_strict
