"""Dependency-backed readiness probe for the API service."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_READINESS_CACHE_TTL_SECONDS = 5.0
_READINESS_TIMEOUT_SECONDS = 3.0
_READINESS_LOCK = asyncio.Lock()
_cached_checks: dict[str, dict[str, Any]] | None = None
_cached_at = 0.0


def _run_checks() -> dict[str, dict[str, Any]]:
    """Run the lightweight-but-real component checks synchronously."""
    from backend.api import main

    checks: dict[str, dict[str, Any]] = {}
    try:
        result = main.transpiler.transpile("SELECT 1 AS readiness_probe", "mysql", "postgres")
        checks["transpiler"] = {"status": "ok" if result.success else "error", "test_result": result.success}
    except Exception:
        logger.exception("Readiness transpiler probe failed")
        checks["transpiler"] = {"status": "error", "code": "probe_failed"}
    try:
        function = main.func_encyclopedia.get_function("CONCAT")
        checks["functions"] = {"status": "ok" if function else "error", "sample_lookup": "CONCAT" if function else None}
    except Exception:
        logger.exception("Readiness function probe failed")
        checks["functions"] = {"status": "error", "code": "probe_failed"}
    try:
        mapping = main.type_mapper.map_type("VARCHAR", "mysql", "postgres")
        checks["types"] = {"status": "ok" if mapping.get("success") else "error", "sample_mapping": mapping.get("target_type")}
    except Exception:
        logger.exception("Readiness type probe failed")
        checks["types"] = {"status": "error", "code": "probe_failed"}
    try:
        generated = main.nl2sql_generator.generate("查询所有用户", "mysql")
        checks["nl2sql"] = {"status": "ok" if generated.success else "error", "confidence": generated.confidence}
    except Exception:
        logger.exception("Readiness NL2SQL probe failed")
        checks["nl2sql"] = {"status": "error", "code": "probe_failed"}
    return checks


async def _get_checks() -> dict[str, dict[str, Any]]:
    """Run at most one expensive probe at a time and reuse it briefly."""
    global _cached_checks, _cached_at
    now = time.monotonic()
    if _cached_checks is not None and now - _cached_at < _READINESS_CACHE_TTL_SECONDS:
        return _cached_checks
    async with _READINESS_LOCK:
        now = time.monotonic()
        if _cached_checks is not None and now - _cached_at < _READINESS_CACHE_TTL_SECONDS:
            return _cached_checks
        try:
            checks = await asyncio.wait_for(asyncio.to_thread(_run_checks), timeout=_READINESS_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error("Readiness probe timed out after %.1fs", _READINESS_TIMEOUT_SECONDS)
            checks = {name: {"status": "error", "code": "probe_timeout"} for name in ("transpiler", "functions", "types", "nl2sql")}
        except Exception:
            logger.exception("Readiness probe failed unexpectedly")
            checks = {"probe": {"status": "error", "code": "probe_failed"}}
        _cached_checks = checks
        _cached_at = time.monotonic()
        return checks


async def readiness_response(request: Request) -> JSONResponse:
    """Return HTTP 200 only when all core service probes pass."""
    checks = await _get_checks()
    failed = [name for name, check in checks.items() if check.get("status") != "ok"]
    return JSONResponse(
        status_code=200 if not failed else 503,
        content={"status": "ready" if not failed else "not_ready", "version": _api_version(), "probe": "readiness", "checks": checks, "timestamp": datetime.now().isoformat()},
    )


def _api_version() -> str:
    """Resolve API version lazily so probe imports do not create startup cycles."""
    from backend.api import main
    return main.API_VERSION
