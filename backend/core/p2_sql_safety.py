"""P2 SQL safety adapters.

Single-statement transpilation is deliberately separated from explicit batch APIs.
"""
from __future__ import annotations

import sqlglot

from .exceptions import ErrorCode
from .transpiler import SQLTranspiler, TranspileResult

_ORIGINAL_TRANSPILE = SQLTranspiler.transpile
_ORIGINAL_VALIDATE_OUTPUT = SQLTranspiler._validate_output


def _transpile_single_statement(self, sql, source, target, *args, **kwargs):
    if isinstance(sql, str) and sql.strip():
        normalized_source = str(source).strip().lower()
        normalized_target = str(target).strip().lower()
        try:
            statements = sqlglot.parse(sql, read=normalized_source)
        except Exception as exc:
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=normalized_source,
                target_dialect=normalized_target,
                error=f"Invalid SQL statement: {str(exc)[:200]}",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        if len(statements) != 1:
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=normalized_source,
                target_dialect=normalized_target,
                error="Multiple SQL statements are not supported; submit one statement per request",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
    return _ORIGINAL_TRANSPILE(self, sql, source, target, *args, **kwargs)


def _validate_single_output(self, sql, dialect):
    try:
        statements = sqlglot.parse(sql, read=dialect)
        if len(statements) != 1:
            return "Output SQL must contain exactly one statement"
    except Exception as exc:
        return f"Output SQL validation failed: {str(exc)[:200]}"
    return _ORIGINAL_VALIDATE_OUTPUT(self, sql, dialect)


if not getattr(SQLTranspiler, "_sdm_p2_single_statement_patch", False):
    SQLTranspiler.transpile = _transpile_single_statement
    SQLTranspiler._validate_output = _validate_single_output
    SQLTranspiler._sdm_p2_single_statement_patch = True
