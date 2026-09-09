"""Dependency-backed readiness probe for the API service."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
import weakref
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_READINESS_CACHE_TTL_SECONDS = 5.0
_READINESS_TIMEOUT_SECONDS = 3.0
_READINESS_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = weakref.WeakKeyDictionary()
_READINESS_LOCKS_GUARD = __import__("threading").Lock()
_READINESS_CACHE = {"checks": None, "cached_at": 0.0}
_HEALTH_PROBE_PATHS = {"/ready", "/health/deep"}


def _probe_allowed(request: Request) -> bool:
    """Allow health probes only from loopback or with the configured probe secret."""
    token = os.getenv("SDM_HEALTH_PROBE_TOKEN", "").strip()
    supplied = request.headers.get("X-Health-Probe-Token", "")
    if token and supplied and secrets.compare_digest(supplied, token):
        return True
    client = request.client
    return bool(client and client.host in {"127.0.0.1", "::1", "localhost"})


def _health_probe_denied_response() -> JSONResponse:
    """Return a stable denial response for public health probe requests."""
    return JSONResponse(
        status_code=403,
        content={
            "success": False,
            "error": {"code": 403, "message": "health probe access denied"},
        },
    )


async def health_probe_response(request: Request) -> JSONResponse:
    """Authorize and dispatch a readiness/deep-health probe request."""
    if request.url.path not in _HEALTH_PROBE_PATHS or request.method not in {"GET", "HEAD"}:
        raise ValueError("health_probe_response called for a non-probe request")
    if not _probe_allowed(request):
        return _health_probe_denied_response()
    if request.url.path == "/ready":
        return await readiness_response(request)
    return await deep_health_response(request)


def _get_readiness_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    with _READINESS_LOCKS_GUARD:
        lock = _READINESS_LOCKS.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _READINESS_LOCKS[loop] = lock
        return lock


def _run_checks() -> dict[str, dict[str, Any]]:
    """Run the lightweight-but-real component checks synchronously."""
    from backend.core.functions_lookup import FunctionEncyclopedia
    from backend.core.nl2sql import NL2SQLGenerator
    from backend.core.transpiler import SQLTranspiler
    from backend.core.type_mapping import TypeMapper

    transpiler = SQLTranspiler()
    function_encyclopedia = FunctionEncyclopedia()
    type_mapper = TypeMapper()
    nl2sql_generator = NL2SQLGenerator()

    checks: dict[str, dict[str, Any]] = {}
    try:
        result = transpiler.transpile("SELECT 1 AS readiness_probe", "mysql", "postgres")
        checks["transpiler"] = {"status": "ok" if result.success else "error", "test_result": result.success}
    except Exception:
        logger.exception("Readiness transpiler probe failed")
        checks["transpiler"] = {"status": "error", "code": "probe_failed"}
    try:
        function = function_encyclopedia.get_function("CONCAT")
        checks["functions"] = {"status": "ok" if function else "error", "sample_lookup": "CONCAT" if function else None}
    except Exception:
        logger.exception("Readiness function probe failed")
        checks["functions"] = {"status": "error", "code": "probe_failed"}
    try:
        mapping = type_mapper.map_type("VARCHAR", "mysql", "postgres")
        checks["types"] = {"status": "ok" if mapping.get("success") else "error", "sample_mapping": mapping.get("target_type")}
    except Exception:
        logger.exception("Readiness type probe failed")
        checks["types"] = {"status": "error", "code": "probe_failed"}
    try:
        generated = nl2sql_generator.generate("查询所有用户", "mysql")
        checks["nl2sql"] = {"status": "ok" if generated.success else "error", "confidence": generated.confidence}
    except Exception:
        logger.exception("Readiness NL2SQL probe failed")
        checks["nl2sql"] = {"status": "error", "code": "probe_failed"}
    return checks


async def _get_checks() -> dict[str, dict[str, Any]]:
    """Run at most one expensive probe at a time per event loop and reuse it briefly."""
    now = time.monotonic()
    cached_checks = globals().get("_cached_checks", _READINESS_CACHE["checks"])
    cached_at = globals().get("_cached_at", _READINESS_CACHE["cached_at"])
    if cached_checks is not None and now - cached_at < _READINESS_CACHE_TTL_SECONDS:
        return cached_checks
    async with _get_readiness_lock():
        now = time.monotonic()
        cached_checks = globals().get("_cached_checks", _READINESS_CACHE["checks"])
        cached_at = globals().get("_cached_at", _READINESS_CACHE["cached_at"])
        if cached_checks is not None and now - cached_at < _READINESS_CACHE_TTL_SECONDS:
            return cached_checks
        try:
            checks = await asyncio.wait_for(asyncio.to_thread(_run_checks), timeout=_READINESS_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error("Readiness probe timed out after %.1fs", _READINESS_TIMEOUT_SECONDS)
            checks = {name: {"status": "error", "code": "probe_timeout"} for name in ("transpiler", "functions", "types", "nl2sql")}
        except Exception:
            logger.exception("Readiness probe failed unexpectedly")
            checks = {"probe": {"status": "error", "code": "probe_failed"}}
        _READINESS_CACHE["checks"] = checks
        _READINESS_CACHE["cached_at"] = time.monotonic()
        globals()["_cached_checks"] = checks
        globals()["_cached_at"] = _READINESS_CACHE["cached_at"]
        return checks


def _response_status(checks: dict[str, dict[str, Any]]) -> tuple[int, bool]:
    """Return the HTTP status and health flag for a probe result."""
    failed = [name for name, check in checks.items() if check.get("status") != "ok"]
    return (200 if not failed else 503, not failed)


async def readiness_response(request: Request) -> JSONResponse:
    """Return HTTP 200 only when all core service probes pass."""
    checks = await _get_checks()
    status_code, healthy = _response_status(checks)
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if healthy else "not_ready",
            "version": _api_version(),
            "probe": "readiness",
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
        },
    )


async def deep_health_response(request: Request) -> JSONResponse:
    """Return deep health using the same cached dependency probes as readiness."""
    checks = await _get_checks()
    status_code, healthy = _response_status(checks)
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "✅ healthy" if healthy else "❌ unhealthy",
            "version": _api_version(),
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
        },
    )


def _api_version() -> str:
    """Resolve API version without importing the API module back into readiness."""
    from core.config import settings

    return settings.api_version
