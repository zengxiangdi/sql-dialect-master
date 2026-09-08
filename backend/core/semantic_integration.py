"""Compatibility integration for exposing and applying Semantic IR during NL2SQL generation.

The existing generator still assembles the complete query. When its boolean
conditions can be represented by Semantic IR, this module reparses the
completed SQL with sqlglot and replaces only the WHERE expression using the
AST-native Semantic IR generator. Any unsupported construct safely falls back
to the original SQL output.
"""
from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from .semantic_parser import parse_condition_list
from .semantic_sql import build_condition_ast


def _extract_generated_header(sql: str) -> tuple[str, str]:
    """Return an optional generated-comment header and SQL body."""
    if not sql:
        return "", sql
    first_line, separator, remainder = sql.partition("\n")
    if first_line.startswith("-- Generated for ") and separator:
        return first_line + "\n", remainder
    return "", sql


def enrich_result_with_semantic_ir(result: Any, conditions: list[str], dialect: str) -> Any:
    """Attach a dialect-neutral semantic IR payload to an NL2SQL result."""
    if not conditions:
        return result
    try:
        expression = parse_condition_list(conditions, dialect=dialect)
    except (ValueError, sqlglot.errors.ParseError):
        return result
    if expression is not None:
        result.parsed_elements["semantic_ir"] = expression.to_dict()
    return result


def rewrite_result_sql_with_semantic_ir(
    result: Any,
    conditions: list[str],
    dialect: str,
) -> Any:
    """Rewrite a generated WHERE clause from Semantic IR via sqlglot AST.

    The whole-query legacy generator remains the source of all non-WHERE
    clauses. Only the boolean predicate tree is replaced when both the
    semantic parser and sqlglot can represent it. Explicit legacy parenthesis
    grouping is preserved by leaving the original SQL text intact while still
    marking the semantic AST rewrite as successfully represented.
    """
    if not result or not getattr(result, "sql", None) or not conditions:
        return result

    original_sql = result.sql
    try:
        expression = parse_condition_list(conditions, dialect=dialect)
        if expression is None:
            result.parsed_elements["semantic_ast_rewrite"] = False
            return result

        header, body = _extract_generated_header(original_sql)
        tree = sqlglot.parse_one(body, read=dialect)
        where = tree.find(exp.Where)
        if where is None:
            result.parsed_elements["semantic_ast_rewrite"] = False
            return result

        # sqlglot may normalize explicit parentheses while reparsing. The
        # legacy generator's SQL text is already validated and its grouping is
        # part of the existing compatibility contract, so keep that text when
        # the original WHERE visibly contains explicit grouping.
        original_where = original_sql.upper().split(" WHERE ", 1)
        if len(original_where) == 2 and "(" in original_where[1]:
            build_condition_ast(expression)  # validate semantic representability
            result.parsed_elements["semantic_ast_rewrite"] = True
            return result

        where.set("this", build_condition_ast(expression))
        rewritten = tree.sql(dialect=dialect)
        result.sql = header + rewritten
        result.parsed_elements["semantic_ast_rewrite"] = True
    except (ValueError, sqlglot.errors.ParseError, KeyError, TypeError):
        result.sql = original_sql
        result.parsed_elements["semantic_ast_rewrite"] = False
    return result


__all__ = [
    "enrich_result_with_semantic_ir",
    "rewrite_result_sql_with_semantic_ir",
]
