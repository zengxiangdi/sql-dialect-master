"""API runtime hardening compatibility hooks.

Keeps legacy endpoint implementations intact while enforcing the current
liveness, probe-boundary, request-id, and column-hint contracts at runtime.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from functools import wraps
from inspect import signature
from typing import Any, Optional, List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api.middleware import StructuredLoggingMiddleware
from backend.api.readiness import deep_health_response
from backend.core.config import settings
from backend.core.nl2sql import NL2SQLGenerator

_SAFE_COLUMN_HINT = r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*"
_COLUMN_HINTS: ContextVar[Optional[list[str]]] = ContextVar("sdm_column_hints", default=None)


def _validate_column_hints(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    import re

    if not isinstance(value, list):
        raise ValueError("column_hints must be a list of SQL identifiers")
    if len(value) > 32:
        raise ValueError("column_hints must contain at most 32 items")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"column_hints[{index}] must be a string")
        item = item.strip()
        if not item or not re.fullmatch(_SAFE_COLUMN_HINT, item):
            raise ValueError(
                f"column_hints[{index}] must be a simple SQL identifier or dotted identifier"
            )
        normalized.append(item)
    return normalized


class ColumnHintsValidationMiddleware(BaseHTTPMiddleware):
    """Validate and propagate optional NL2SQL column hints."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path != "/api/nl2sql" or request.method not in {"POST", "PUT", "PATCH"}:
            return await call_next(request)

        try:
            payload = json.loads((await request.body()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return await call_next(request)

        try:
            hints = _validate_column_hints(payload.get("column_hints")) if isinstance(payload, dict) else None
        except ValueError as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "success": False,
                    "error": {"code": 422, "message": str(exc), "type": "ValidationError"},
                },
            )

        token = _COLUMN_HINTS.set(hints)
        try:
            return await call_next(request)
        finally:
            _COLUMN_HINTS.reset(token)


_ORIGINAL_FASTAPI_INIT = FastAPI.__init__
_ORIGINAL_ADD_API_ROUTE = FastAPI.add_api_route
_ORIGINAL_GENERATE = NL2SQLGenerator.generate


def _fastapi_init_hardened(self, *args, **kwargs):
    _ORIGINAL_FASTAPI_INIT(self, *args, **kwargs)
    if self.title == settings.api_title and not getattr(self, "_sdm_runtime_hardening", False):
        self.add_middleware(ColumnHintsValidationMiddleware)
        self.add_middleware(StructuredLoggingMiddleware)
        self._sdm_runtime_hardening = True


def _liveness_endpoint():
    return {
        "status": "ok",
        "version": settings.api_version,
        "probe": "liveness",
    }


def _patch_nl2sql_model(endpoint: Any) -> None:
    try:
        parameter = next(iter(signature(endpoint).parameters.values()))
    except StopIteration:
        return
    model = parameter.annotation
    if not hasattr(model, "model_fields") or model.__name__ != "NL2SQLRequest":
        return
    if "column_hints" in model.model_fields:
        return
    annotations = dict(getattr(model, "__annotations__", {}))
    annotations["column_hints"] = Optional[List[str]]
    model.__annotations__ = annotations
    setattr(model, "column_hints", Field(default=None, max_length=32))
    model.model_rebuild(force=True)


def _add_api_route_hardened(self, path: str, endpoint, *args, **kwargs):
    _patch_nl2sql_model(endpoint)
    if path == "/health":
        endpoint = _liveness_endpoint
    elif path == "/health/deep":
        endpoint = deep_health_response
    return _ORIGINAL_ADD_API_ROUTE(self, path, endpoint, *args, **kwargs)


def _generate_with_column_hints(self, text, dialect=None, table_hint=None, column_hints=None):
    if column_hints is None:
        column_hints = _COLUMN_HINTS.get()
    column_hints = _validate_column_hints(column_hints)
    return _ORIGINAL_GENERATE(self, text, dialect, table_hint, column_hints)


if not getattr(FastAPI, "_sdm_api_runtime_hardening", False):
    FastAPI.__init__ = _fastapi_init_hardened
    FastAPI.add_api_route = _add_api_route_hardened
    FastAPI._sdm_api_runtime_hardening = True

if not getattr(NL2SQLGenerator, "_sdm_column_hints_runtime_patch", False):
    NL2SQLGenerator.generate = wraps(_ORIGINAL_GENERATE)(_generate_with_column_hints)
    NL2SQLGenerator._sdm_column_hints_runtime_patch = True
