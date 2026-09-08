"""Second-pass production hardening helpers."""

import os

from .config import settings
from .nl2sql import NL2SQLGenerator, NL2SQLResult
from .parser import SQLParser, ParseResult
from .transpiler import SQLTranspiler


def _configured_positive_int(env_name: str, default: int) -> int:
    """Read a positive integer configuration value without silently accepting invalid input."""
    raw = os.getenv(env_name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{env_name} must be a positive integer")
    return value


PARSER_MAX_INPUT_LENGTH = _configured_positive_int(
    "SDM_PARSER_MAX_SQL_LENGTH",
    getattr(settings, "parser_max_sql_length", settings.transpiler_max_sql_length),
)
NL2SQL_MAX_INPUT_LENGTH = _configured_positive_int(
    "SDM_NL2SQL_MAX_INPUT_LENGTH",
    getattr(settings, "nl2sql_max_input_length", 8192),
)

_original_parser_parse = SQLParser.parse
_original_nl2sql_generate = NL2SQLGenerator.generate


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
    """Validate output in the target dialect, with only a known parser limitation exempted."""
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


SQLParser.parse = _parse_with_length_guard
NL2SQLGenerator.generate = _generate_with_length_guard
SQLTranspiler._validate_output = _validate_output_strict
