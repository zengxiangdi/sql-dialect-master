"""Compatibility adapter for legacy NL2SQL column-hint validation."""
from __future__ import annotations

from backend.core.column_hint_validation import validate_column_hints
from backend.core.nl2sql import NL2SQLGenerator, NL2SQLResult


_ORIGINAL_NL2SQL_GENERATE = NL2SQLGenerator.generate


def _generate_with_column_hint_validation(
    self, text, dialect=None, table_hint=None, column_hints=None
):
    error = validate_column_hints(column_hints)
    if error:
        return NL2SQLResult(
            success=False,
            input_text=text if isinstance(text, str) else "",
            dialect=dialect or self.default_dialect,
            explanation=error,
            confidence=0.0,
        )
    return _ORIGINAL_NL2SQL_GENERATE(self, text, dialect, table_hint, column_hints)


if not getattr(NL2SQLGenerator, "_sdm_column_hints_validation", False):
    NL2SQLGenerator.generate = _generate_with_column_hint_validation
    NL2SQLGenerator._sdm_column_hints_validation = True
