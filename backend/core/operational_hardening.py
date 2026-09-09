"""Final operational hardening for health probes, NL2SQL hints, and legacy rewrites."""
from __future__ import annotations

import json
import os
import re
import secrets
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.api import readiness
from backend.api.middleware import RateLimitMiddleware, StructuredLoggingMiddleware
from backend.core.column_hint_validation import validate_column_hints
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.post_processor import PostProcessor
from backend.core.p1_sql_scanner import mask_non_executable


def _probe_allowed(request: Any) -> bool:
    """Allow probes only from loopback or with an explicitly configured secret."""
    token = os.getenv("SDM_HEALTH_PROBE_TOKEN", "").strip()
    supplied = request.headers.get("X-Health-Probe-Token", "")
    if token and supplied and secrets.compare_digest(supplied, token):
        return True
    client = request.client
    return bool(client and client.host in {"127.0.0.1", "::1", "localhost"})


_ORIGINAL_NL2SQL_GENERATE = NL2SQLGenerator.generate


def _generate_with_column_hint_validation(self, text, dialect=None, table_hint=None, column_hints=None):
    error = validate_column_hints(column_hints)
    if error:
        from backend.core.nl2sql import NL2SQLResult
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


def _convert_rownum_scanned(self, sql: str):
    """Convert only an executable ROWNUM predicate; never rewrite literals/comments."""
    notes = []
    masked = mask_non_executable(sql)
    match = re.search(r"ROWNUM\s*<=?\s*(\d+)", masked, re.IGNORECASE)
    if not match:
        return sql, notes

    n = match.group(1)
    start, end = match.span()
    before = sql[:start]
    after = sql[end:]
    masked_before = masked[:start]

    boundary = re.search(r"(?:\bWHERE\s*|\bAND\s*)$", masked_before, re.IGNORECASE)
    if boundary:
        before = before[:boundary.start()]

    result = before + after
    masked_result = mask_non_executable(result)
    if "LIMIT" not in masked_result.upper():
        result = result.rstrip(";").rstrip() + f" LIMIT {n}"
    notes.append(f"Converted ROWNUM to LIMIT {n}")
    return result, notes


if not getattr(PostProcessor, "_sdm_rownum_scanner_patch", False):
    PostProcessor._convert_rownum_to_limit = _convert_rownum_scanned
    PostProcessor._sdm_rownum_scanner_patch = True


_ORIGINAL_RATE_LIMIT_DISPATCH = RateLimitMiddleware.dispatch


async def _dispatch_health_hardened(self, request, call_next):
    if request.url.path in {"/ready", "/health/deep"} and request.method in {"GET", "HEAD"}:
        if not _probe_allowed(request):
            return JSONResponse(
                status_code=403,
                content={"success": False, "error": {"code": 403, "message": "health probe access denied"}},
            )
        if request.url.path == "/ready":
            return await readiness.readiness_response(request)
        checks = await readiness._get_checks()
        failed = [name for name, check in checks.items() if check.get("status") != "ok"]
        return JSONResponse(
            status_code=503 if failed else 200,
            content={
                "status": "❌ unhealthy" if failed else "✅ healthy",
                "version": readiness._api_version(),
                "checks": checks,
            },
        )

    if request.url.path == "/api/nl2sql" and request.method == "POST":
        body = await request.body()
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return await _ORIGINAL_RATE_LIMIT_DISPATCH(self, request, call_next)
        error = validate_column_hints(payload.get("column_hints")) if isinstance(payload, dict) else None
        if error:
            return JSONResponse(
                status_code=422,
                content={"success": False, "error": {"code": "VALIDATION_FAILED", "message": error}},
            )

    return await _ORIGINAL_RATE_LIMIT_DISPATCH(self, request, call_next)


if not getattr(RateLimitMiddleware, "_sdm_operational_health_patch", False):
    RateLimitMiddleware.dispatch = _dispatch_health_hardened
    RateLimitMiddleware._sdm_operational_health_patch = True


_ORIGINAL_FASTAPI_INIT = FastAPI.__init__


def _fastapi_init_with_structured_logging(self, *args, **kwargs):
    _ORIGINAL_FASTAPI_INIT(self, *args, **kwargs)
    if not any(m.cls is StructuredLoggingMiddleware for m in self.user_middleware):
        self.add_middleware(StructuredLoggingMiddleware)


if not getattr(FastAPI, "_sdm_structured_logging_patch", False):
    FastAPI.__init__ = _fastapi_init_with_structured_logging
    FastAPI._sdm_structured_logging_patch = True
