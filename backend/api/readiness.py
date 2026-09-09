"""Cached readiness/deep-health probes with internal access controls."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import os
import time
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_PROBE_CACHE_TTL_SECONDS = 5.0
_PROBE_TIMEOUT_SECONDS = 3.0
_PROBE_LOCK = asyncio.Lock()
_PROBE_AUTH_HEADER = "x-probe-token"
_PROBE_AUTH_ENV = "SDM_PROBE_TOKEN"
_cached_checks: dict[str, dict[str, Any]] | None = None
_cached_at = 0.0


def _probe_allowed(request: Request) -> bool:
    configured = os.getenv(_PROBE_AUTH_ENV, "").strip()
    if configured:
        return hmac.compare_digest(
            request.headers.get(_PROBE_AUTH_HEADER, ""), configured
        )
    host = request.client.host if request.client else ""
    if host in {"testclient", "localhost"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def _probe_denied() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        headers={"Cache-Control": "no-store"},
        content={
            "success": False,
            "error": {"code": 403, "message": "Probe endpoint is internal-only"},
            "timestamp": datetime.now().isoformat(),
        },
    )


def _failure_checks(code: str) -> dict[str, dict[str, str]]:
    return {
        name: {
            "status": "error",
            "code": code,
        }
        for name in ("transpiler", "functions", "types", "nl2sql")
    }


def _run_checks() -> dict[str, dict[str, Any]]:
    """Run the lightweight-but-real component checks synchronously."""
    from backend.api import main

    checks: dict[str, dict[str, Any]] = {}
    try:
        result = main.transpiler.transpile(
            "SELECT 1 AS readiness_probe", "mysql", "postgres"
        )
        checks["transpiler"] = {
            "status": "ok" if result.success else "error",
            "test_result": result.success,
        }
    except Exception:
        logger.exception("Readiness transpiler probe failed")
        checks["transpiler"] = {"status": "error", "code": "probe_failed"}

    try:
        function = main.func_encyclopedia.get_function("CONCAT")
        checks["functions"] = {
            "status": "ok" if function else "error",
            "sample_lookup": "CONCAT" if function else None,
        }
    except Exception:
        logger.exception("Readiness function probe failed")
        checks["functions"] = {"status": "error", "code": "probe_failed"}

    try:
        mapping = main.type_mapper.map_type("VARCHAR", "mysql", "postgres")
        checks["types"] = {
            "status": "ok" if mapping.get("success") else "error",
            "sample_mapping": mapping.get("target_type"),
        }
    except Exception:
        logger.exception("Readiness type probe failed")
        checks["types"] = {"status": "error", "code": "probe_failed"}

    try:
        generated = main.nl2sql_generator.generate("查询所有用户", "mysql")
        checks["nl2sql"] = {
            "status": "ok" if generated.success else "error",
            "confidence": generated.confidence,
        }
    except Exception:
        logger.exception("Readiness NL2SQL probe failed")
        checks["nl2sql"] = {"status": "error", "code": "probe_failed"}

    return checks


async def _get_checks() -> dict[str, dict[str, Any]]:
    """Reuse probe results briefly and allow only one in-flight probe."""
    global _cached_checks, _cached_at

    now = time.monotonic()
    if _cached_checks is not None and now - _cached_at < _PROBE_CACHE_TTL_SECONDS:
        return _cached_checks

    async with _PROBE_LOCK:
        now = time.monotonic()
        if _cached_checks is not None and now - _cached_at < _PROBE_CACHE_TTL_SECONDS:
            return _cached_checks
        try:
            checks = await asyncio.wait_for(
                asyncio.to_thread(_run_checks), timeout=_PROBE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error("Health probe timed out after %.1fs", _PROBE_TIMEOUT_SECONDS)
            checks = _failure_checks("probe_timeout")
        except Exception:
            logger.exception("Health probe failed unexpectedly")
            checks = _failure_checks("probe_failed")
        _cached_checks = checks
        _cached_at = time.monotonic()
        return checks


def _result_response(
    checks: dict[str, dict[str, Any]], probe: str
) -> JSONResponse:
    healthy = bool(checks) and all(
        check.get("status") == "ok" for check in checks.values()
    )
    status = "ready" if probe == "readiness" and healthy else "not_ready"
    if probe == "deep":
        status = "✅ healthy" if healthy else "❌ unhealthy"
    return JSONResponse(
        status_code=200 if healthy else 503,
        headers={"Cache-Control": "no-store"},
        content={
            "status": status,
            "version": _api_version(),
            "probe": probe,
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
        },
    )


async def readiness_response(request: Request) -> JSONResponse:
    if not _probe_allowed(request):
        return _probe_denied()
    return _result_response(await _get_checks(), "readiness")


async def deep_health_response(request: Request) -> JSONResponse:
    if not _probe_allowed(request):
        return _probe_denied()
    return _result_response(await _get_checks(), "deep")


def _api_version() -> str:
    from backend.api import main

    return main.API_VERSION
