"""Core transpiler input validation helpers."""

from typing import Any

from .exceptions import ErrorCode, ValidationError
from .transpiler import SQLTranspiler, TranspileResult


_original_transpile = SQLTranspiler.transpile


def _validate_transpile_inputs(sql: Any, source: Any, target: Any) -> None:
    """Reject invalid core transpile arguments before string operations."""
    if not isinstance(sql, str):
        raise ValidationError(
            "sql must be a string",
            field="sql",
            value=type(sql).__name__,
        )
    if not isinstance(source, str):
        raise ValidationError(
            "source must be a string",
            field="source",
            value=type(source).__name__,
        )
    if not isinstance(target, str):
        raise ValidationError(
            "target must be a string",
            field="target",
            value=type(target).__name__,
        )


def _transpile_validated(
    self: SQLTranspiler,
    sql: str,
    source: str,
    target: str,
    pretty: bool = True,
    validate: bool = True,
    skip_security: bool = False,
) -> TranspileResult:
    """Validate inputs before delegating to the transpiler implementation."""
    try:
        _validate_transpile_inputs(sql, source, target)
    except ValidationError as exc:
        return TranspileResult(
            success=False,
            source_sql=sql if isinstance(sql, str) else str(sql),
            source_dialect=source if isinstance(source, str) else str(source),
            target_dialect=target if isinstance(target, str) else str(target),
            error=str(exc),
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return _original_transpile(
        self, sql, source, target, pretty, validate, skip_security
    )


SQLTranspiler.transpile = _transpile_validated
