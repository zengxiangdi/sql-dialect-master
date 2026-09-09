"""P1 hardening adapter for stacked-statement correctness.

SQL custom transformations live in ``PostProcessor`` and are scanner-aware.
This adapter only preserves the legacy core transpiler boundary for rejecting
multi-statement input before the original transpiler can silently keep the
first statement.
"""

from __future__ import annotations

import logging

import sqlglot

from .config import settings
from .exceptions import ErrorCode
from .transpiler import SQLTranspiler, TranspileResult

logger = logging.getLogger(__name__)

_ORIGINAL_TRANSPILER = SQLTranspiler.transpile


def _reject_stacked_statements(
    self,
    sql: str,
    source: str,
    target: str,
) -> TranspileResult | None:
    """Reject stacked SQL statements instead of silently returning statement #1."""
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
    """Enforce a single executable SQL statement at the transpiler boundary."""
    if not isinstance(source, str) or not isinstance(target, str):
        return _ORIGINAL_TRANSPILER(
            self,
            sql,
            source,
            target,
            pretty,
            validate,
            skip_security,
        )

    source_normalized = source.strip().lower()
    target_normalized = target.strip().lower()

    # Keep security validation precedence over stacked-query rejection.
    if self._security_enabled and not skip_security and isinstance(sql, str):
        security_result = self._validate_security(sql)
        if security_result["blocked"]:
            return _ORIGINAL_TRANSPILER(
                self,
                sql,
                source,
                target,
                pretty,
                validate,
                skip_security,
            )

    rejection = _reject_stacked_statements(
        self,
        sql,
        source_normalized,
        target_normalized,
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


if not getattr(SQLTranspiler, "_sdm_p1_single_statement_patch", False):
    SQLTranspiler.transpile = _transpile_single_statement
    SQLTranspiler._sdm_p1_single_statement_patch = True
