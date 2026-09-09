"""Compatibility fix for strict single-statement output validation."""
from __future__ import annotations

from typing import Optional

import sqlglot

from .transpiler import SQLTranspiler


def _validate_output(self: SQLTranspiler, sql: str, dialect: str) -> Optional[str]:
    """Require exactly one parseable output statement with dialect context."""
    try:
        statements = [statement for statement in sqlglot.parse(sql, read=dialect) if statement is not None]
    except Exception as exc:
        return f"⚠️ {dialect} dialect validation failed: {str(exc)[:100]}"

    if len(statements) != 1:
        return (
            f"⚠️ {dialect} dialect validation failed: output must contain "
            f"exactly one statement; found {len(statements)}"
        )
    return None


if not getattr(SQLTranspiler, "_sdm_single_statement_output_validation", False):
    SQLTranspiler._validate_output = _validate_output
    SQLTranspiler._sdm_single_statement_output_validation = True
