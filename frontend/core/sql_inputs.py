"""Shared input validation for the static SQL workspaces."""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from backend.core.config import settings


def parse_single_sql(sql: str, dialect: str) -> exp.Expression:
    """Parse the entire input and require one bounded SQL statement."""
    if not isinstance(sql, str):
        raise sqlglot.errors.ParseError("SQL must be a string")
    maximum = settings.parser_max_sql_length
    if len(sql) > maximum:
        raise sqlglot.errors.ParseError(f"SQL exceeds maximum length of {maximum} characters")
    raw_statements = sqlglot.parse(sql, read=dialect)
    if any(item is None for item in raw_statements):
        raise sqlglot.errors.ParseError("Multiple or empty SQL statements are not supported.")
    if len(raw_statements) == 2 and isinstance(raw_statements[1], exp.Semicolon):
        raw_statements = raw_statements[:1]
    elif any(isinstance(item, exp.Semicolon) for item in raw_statements):
        raise sqlglot.errors.ParseError("Multiple SQL statements are not supported.")
    statements = raw_statements
    if not statements:
        raise sqlglot.errors.ParseError("Please enter SQL to analyze.")
    if len(statements) != 1:
        raise sqlglot.errors.ParseError("Multiple SQL statements are not supported.")
    return statements[0]
