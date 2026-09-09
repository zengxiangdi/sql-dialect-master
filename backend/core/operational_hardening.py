"""Compatibility adapter for legacy NL2SQL validation and app middleware."""
from __future__ import annotations

from fastapi import FastAPI

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


_ORIGINAL_FASTAPI_INIT = FastAPI.__init__


def _fastapi_init_with_structured_logging(self, *args, **kwargs):
    _ORIGINAL_FASTAPI_INIT(self, *args, **kwargs)
    from backend.api.middleware import StructuredLoggingMiddleware

    if not any(middleware.cls is StructuredLoggingMiddleware for middleware in self.user_middleware):
        self.add_middleware(StructuredLoggingMiddleware)


if not getattr(FastAPI, "_sdm_structured_logging_registration", False):
    FastAPI.__init__ = _fastapi_init_with_structured_logging
    FastAPI._sdm_structured_logging_registration = True
