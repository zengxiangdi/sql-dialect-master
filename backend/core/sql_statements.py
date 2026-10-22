"""Shared bounded parsing contract for single SQL statements."""
from __future__ import annotations

from typing import cast

import sqlglot
from sqlglot import exp

from .config import settings
from .p1_sql_scanner import prepare_sql_for_parser


def parse_single_sql(sql: str, dialect: str) -> exp.Expression:
    """Accept one statement and an optional delimiter followed by a comment."""
    if not isinstance(sql, str):
        raise sqlglot.errors.ParseError("SQL statement must be a string")
    if not sql.strip():
        raise sqlglot.errors.ParseError("Empty SQL statement")
    # AppSettings' after validator resolves the optional parser limit.
    maximum = cast(int, settings.parser_max_sql_length)
    if len(sql) > maximum:
        raise sqlglot.errors.ParseError(f"SQL exceeds maximum length of {maximum} characters")
    statements = sqlglot.parse(prepare_sql_for_parser(sql, dialect), read=dialect)
    if any(statement is None for statement in statements):
        raise sqlglot.errors.ParseError("Multiple or empty SQL statements are not supported")
    # sqlglot represents a trailing comment after `;` as a Semicolon AST.
    if len(statements) == 2 and isinstance(statements[1], exp.Semicolon):
        statements = statements[:1]
    if not statements:
        raise sqlglot.errors.ParseError("Empty SQL statement")
    if len(statements) != 1 or isinstance(statements[0], exp.Semicolon):
        raise sqlglot.errors.ParseError("Multiple SQL statements are not supported")
    # The empty-statement guard above has already excluded None entries.
    return cast(exp.Expression, statements[0])
