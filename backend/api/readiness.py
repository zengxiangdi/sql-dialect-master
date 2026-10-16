"""Dependency-backed readiness probe for the API service."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import threading
import time
import uuid
import weakref
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

from backend.core.config import settings

_READINESS_CACHE_TTL_SECONDS = 5.0
_READINESS_TIMEOUT_SECONDS = 3.0
_READINESS_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = weakref.WeakKeyDictionary()
_READINESS_LOCKS_GUARD = threading.Lock()
_READINESS_CACHE = {"checks": None, "cached_at": 0.0}
_HEALTH_PROBE_PATHS = {"/ready", "/health/deep"}

# The probe cache intentionally expires quickly so readiness reflects a
# degraded dependency within a few seconds.  Constructing the probe services,
# however, is much more expensive than running their checks: the function/type
# catalogs are parsed from JSON and the NL2SQL pipeline builds several indexes.
# Keep those immutable-for-the-process services alive and only rerun the cheap
# health operations on each refresh.  A regular threading lock is required
# because ``_run_checks`` executes in a worker thread and multiple ASGI event
# loops can call this module in the same process (for example during tests).
_PROBE_SERVICES: tuple[Any, Any, Any, Any] | None = None
_PROBE_SERVICES_LOCK = threading.Lock()


def _probe_allowed(request: Request) -> bool:
    """Allow health probes only from loopback or with the configured probe secret."""
    configured = settings.health_probe_token
    token = configured.get_secret_value().strip() if configured else ""
    # Keep process-level test/dev overrides effective after module import;
    # production configuration still comes from the validated singleton above
    # (including values loaded from .env).
    if not token:
        token = os.environ.get("SDM_HEALTH_PROBE_TOKEN", "").strip()
    supplied = request.headers.get("X-Health-Probe-Token", "")
    if token and supplied and secrets.compare_digest(supplied, token):
        return True
    # Once a token is configured, require it even for loopback callers.  This
    # avoids trusting an unverified X-Forwarded-For chain in front of a proxy.
    if token:
        return False
    client = request.client
    return bool(client and client.host in {"127.0.0.1", "::1", "localhost"})


def _health_probe_denied_response(request: Request) -> JSONResponse:
    """Return a stable denial response for public health probe requests."""
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    headers = {"X-Request-ID": request_id}
    content = {
        "success": False,
        "error": {"code": 403, "message": "health probe access denied"},
    }
    content["request_id"] = request_id
    return JSONResponse(
        status_code=403,
        content=content,
        headers=headers,
    )


async def health_probe_response(request: Request) -> JSONResponse:
    """Authorize and dispatch a readiness/deep-health probe request."""
    if request.url.path not in _HEALTH_PROBE_PATHS or request.method not in {"GET", "HEAD"}:
        raise ValueError("health_probe_response called for a non-probe request")
    if not _probe_allowed(request):
        return _health_probe_denied_response(request)
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


def _get_probe_services():
    """Return lazily initialized probe services shared by all refreshes."""
    global _PROBE_SERVICES
    if _PROBE_SERVICES is not None:
        return _PROBE_SERVICES

    from backend.core.functions_lookup import FunctionEncyclopedia
    from backend.core.nl2sql import NL2SQLGenerator
    from backend.core.transpiler import SQLTranspiler
    from backend.core.type_mapping import TypeMapper

    with _PROBE_SERVICES_LOCK:
        # Double-check after acquiring the lock so concurrent worker threads
        # do not each reload the catalog files.
        if _PROBE_SERVICES is None:
            _PROBE_SERVICES = (
                SQLTranspiler(),
                FunctionEncyclopedia(),
                TypeMapper(),
                NL2SQLGenerator(),
            )
        return _PROBE_SERVICES


def _run_checks() -> dict[str, dict[str, Any]]:
    """Run the lightweight-but-real component checks synchronously."""
    (
        transpiler,
        function_encyclopedia,
        type_mapper,
        nl2sql_generator,
    ) = _get_probe_services()

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
    cached_checks = _READINESS_CACHE["checks"]
    cached_at = _READINESS_CACHE["cached_at"]
    if cached_checks is not None and now - cached_at < _READINESS_CACHE_TTL_SECONDS:
        return cached_checks
    async with _get_readiness_lock():
        now = time.monotonic()
        cached_checks = _READINESS_CACHE["checks"]
        cached_at = _READINESS_CACHE["cached_at"]
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
    from backend.core.config import settings

    return settings.api_version
