"""Validation helpers for NL2SQL column hints."""
from __future__ import annotations

import re
from typing import Iterable, Optional

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*$")
_ALLOWED_EXPRESSION = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_$]*|[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*)$")


def validate_column_hints(column_hints: Optional[Iterable[str]]) -> Optional[str]:
    """Return a validation error, or None for absent/valid column hints."""
    if column_hints is None:
        return None
    if not isinstance(column_hints, (list, tuple)):
        return "column_hints must be a list of column identifiers"
    for index, column in enumerate(column_hints):
        if not isinstance(column, str) or not column.strip():
            return f"column_hints[{index}] must be a non-empty string"
        normalized = column.strip()
        if not _IDENTIFIER.fullmatch(normalized) or not _ALLOWED_EXPRESSION.fullmatch(normalized):
            return f"column_hints[{index}] is not a valid column identifier"
    return None
