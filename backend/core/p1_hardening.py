"""P1 hardening adapters for correctness and resource safety.

These adapters are intentionally small and idempotent so they can be removed
once the underlying implementation is refactored without compatibility layers.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

import sqlglot

from .audit_hardening import _mask_non_executable, _replace_outside
from .config import settings
from .exceptions import ErrorCode
from .post_processor import PostProcessor
from .transpiler import SQLTranspiler, TranspileResult

logger = logging.getLogger(__name__)


_ORIGINAL_TRANSPILER = SQLTranspiler.transpile
_ORIGINAL_TOP_TO_LIMIT = PostProcessor._convert_top_to_limit
_ORIGINAL_GROUP_CONCAT = PostProcessor._fix_group_concat_default_separator


def _reject_stacked_statements(
    self,
    sql: str,
    source: str,
    target: str,
    pretty: bool = True,
    validate: bool = True,
    skip_security: bool = False,
) -> TranspileResult | None:
    """Reject multi-statement input instead of silently returning statement #1."""
    if not isinstance(sql, str) or not sql.strip():
        return None
    if len(sql) > settings.transpiler_max_sql_length:
        return None

    try:
        statements = sqlglot.parse(sql, read=source)
    except Exception:
        # Preserve the original transpiler's parser/error handling.
        return None

    if len(statements) <= 1:
        return None

    logger.warning("Rejecting stacked SQL statements: count=%s", len(statements))
    return TranspileResult(
        success=False,
        source_sql=sql,
        source_dialect=source,
        target_dialect=target,
        error="Multiple SQL statements are not supported; submit one statement per request",
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


def _transpile_single_statement(
    self,
    sql: str,
    source: str,
    target: str,
    pretty: bool = True,
    validate: bool = True,
    skip_security: bool = False,
):
    source_normalized = source.strip().lower()
    target_normalized = target.strip().lower()
    rejection = _reject_stacked_statements(
        self,
        sql,
        source_normalized,
        target_normalized,
        pretty,
        validate,
        skip_security,
    )
    if rejection is not None:
        return rejection
    return _ORIGINAL_TRANSPILER(
        self,
        sql,
        source,
        target,
        pretty,
        validate,
        skip_security,
    )


def _convert_top_to_limit_quote_aware(self, sql: str):
    """Convert SQL Server TOP only in executable SQL segments."""
    masked = _mask_non_executable(sql)
    match = re.search(r"SELECT\s+TOP\s+(\d+)", masked, re.IGNORECASE)
    if not match:
        return _ORIGINAL_TOP_TO_LIMIT(self, sql)

    n = match.group(1)
    result, count = _replace_outside(
        sql,
        re.compile(r"SELECT\s+TOP\s+\d+", re.IGNORECASE),
        "SELECT",
    )
    if not count:
        return sql, []

    masked_result = _mask_non_executable(result)
    if "LIMIT" not in masked_result.upper():
        result = result.rstrip(";").rstrip() + f" LIMIT {n}"

    return result, [f"Converted TOP {n} to LIMIT {n}"]


def _fix_group_concat_quote_aware(self, sql: str):
    """Fix the legacy simple GROUP_CONCAT case without touching literals/comments."""
    pattern = re.compile(r"GROUP_CONCAT\s*\((\w+)\)(?!\s+SEPARATOR)", re.IGNORECASE)

    def add_default_separator(match: re.Match) -> str:
        col = match.group(1)
        return f"STRING_AGG({col}::TEXT, ',')"

    result, count = _replace_outside(sql, pattern, add_default_separator)
    if not count:
        return _ORIGINAL_GROUP_CONCAT(self, sql)
    return result, ["Converted GROUP_CONCAT to STRING_AGG with default separator"]


if not getattr(SQLTranspiler, "_sdm_p1_single_statement_patch", False):
    SQLTranspiler.transpile = _transpile_single_statement
    SQLTranspiler._sdm_p1_single_statement_patch = True

if not getattr(PostProcessor, "_sdm_p1_top_to_limit_patch", False):
    PostProcessor._convert_top_to_limit = _convert_top_to_limit_quote_aware
    PostProcessor._sdm_p1_top_to_limit_patch = True

if not getattr(PostProcessor, "_sdm_p1_group_concat_patch", False):
    PostProcessor._fix_group_concat_default_separator = _fix_group_concat_quote_aware
    PostProcessor._sdm_p1_group_concat_patch = True
