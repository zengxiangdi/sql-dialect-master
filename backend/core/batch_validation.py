"""Batch transpile input validation helpers."""

from typing import List

from .config import settings
from .exceptions import ValidationError
from .transpiler import SQLTranspiler, TranspileResult


_original_batch_transpile = SQLTranspiler.batch_transpile
_original_batch_transpile_async = SQLTranspiler.batch_transpile_async


def _validate_batch_size(statements: List[str]) -> None:
    """Reject oversized batches instead of silently dropping statements."""
    if len(statements) > settings.max_batch_size:
        raise ValidationError(
            f"Batch contains {len(statements)} statements; maximum is "
            f"{settings.max_batch_size}",
            field="statements",
            value=str(len(statements)),
        )


def _validate_max_concurrent(max_concurrent: int) -> None:
    """Reject non-positive async concurrency to prevent semaphore deadlocks."""
    if max_concurrent <= 0:
        raise ValidationError(
            f"max_concurrent must be positive; got {max_concurrent}",
            field="max_concurrent",
            value=str(max_concurrent),
        )


def _batch_transpile_validated(
    self: SQLTranspiler,
    statements: List[str],
    source: str,
    target: str,
    pretty: bool = True,
) -> List[TranspileResult]:
    """Validate batch size before delegating to the core implementation."""
    _validate_batch_size(statements)
    return _original_batch_transpile(self, statements, source, target, pretty)


async def _batch_transpile_async_validated(
    self: SQLTranspiler,
    statements: List[str],
    source: str,
    target: str,
    pretty: bool = True,
    max_concurrent: int = 10,
) -> List[TranspileResult]:
    """Validate batch inputs before delegating to the async implementation."""
    _validate_batch_size(statements)
    _validate_max_concurrent(max_concurrent)
    return await _original_batch_transpile_async(
        self, statements, source, target, pretty, max_concurrent
    )


SQLTranspiler.batch_transpile = _batch_transpile_validated
SQLTranspiler.batch_transpile_async = _batch_transpile_async_validated
