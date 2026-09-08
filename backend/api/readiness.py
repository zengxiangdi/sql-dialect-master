"""Dependency-backed readiness probe for the API service."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


def _run_checks() -> dict[str, dict[str, Any]]:
    """Run the lightweight-but-real component checks synchronously."""
    from backend.api import main

    checks: dict[str, dict[str, Any]] = {}

    try:
        result = main.transpiler.transpile("SELECT 1 AS readiness_probe", "mysql", "postgres")
        checks["transpiler"] = {
            "status": "ok" if result.success else "error",
            "test_result": result.success,
        }
    except Exception as exc:
        checks["transpiler"] = {"status": "error", "message": str(exc)}

    try:
        function = main.func_encyclopedia.get_function("CONCAT")
        checks["functions"] = {
            "status": "ok" if function else "error",
            "sample_lookup": "CONCAT" if function else None,
        }
    except Exception as exc:
        checks["functions"] = {"status": "error", "message": str(exc)}

    try:
        mapping = main.type_mapper.map_type("VARCHAR", "mysql", "postgres")
        checks["types"] = {
            "status": "ok" if mapping.get("success") else "error",
            "sample_mapping": mapping.get("target_type"),
        }
    except Exception as exc:
        checks["types"] = {"status": "error", "message": str(exc)}

    try:
        generated = main.nl2sql_generator.generate("查询所有用户", "mysql")
        checks["nl2sql"] = {
            "status": "ok" if generated.success else "error",
            "confidence": generated.confidence,
        }
    except Exception as exc:
        checks["nl2sql"] = {"status": "error", "message": str(exc)}

    return checks


async def readiness_response(request: Request) -> JSONResponse:
    """Return HTTP 200 only when all core service probes pass."""
    checks = await asyncio.to_thread(_run_checks)
    failed = [name for name, check in checks.items() if check.get("status") != "ok"]
    status = "ready" if not failed else "not_ready"
    return JSONResponse(
        status_code=200 if not failed else 503,
        content={
            "status": status,
            "version": _api_version(),
            "probe": "readiness",
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
        },
    )


def _api_version() -> str:
    """Resolve API version lazily so probe imports do not create startup cycles."""
    from backend.api import main

    return main.API_VERSION
