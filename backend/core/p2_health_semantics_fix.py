"""Compatibility fix for deep-health response sanitization."""
from __future__ import annotations

import json

from fastapi.responses import JSONResponse

from backend.api.middleware import RateLimitMiddleware

_ORIGINAL_DISPATCH = RateLimitMiddleware.dispatch


async def _dispatch(self, request, call_next):
    response = await _ORIGINAL_DISPATCH(self, request, call_next)
    if request.url.path != "/health/deep":
        return response
    try:
        raw_body = b"".join([chunk async for chunk in response.body_iterator])
        payload = json.loads(raw_body.decode("utf-8"))
        if isinstance(payload, dict):
            checks = payload.get("checks")
            if isinstance(checks, dict):
                for check in checks.values():
                    if isinstance(check, dict) and "message" in check:
                        check["message"] = "internal health check failure"
            if payload.get("status") == "❌ unhealthy":
                status = 503
            else:
                status = response.status_code
            return JSONResponse(
                status_code=status,
                content=payload,
                headers={key: value for key, value in response.headers.items() if key.lower() != "content-length"},
            )
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return response
    return response


if not getattr(RateLimitMiddleware, "_sdm_p2_health_semantics_fix", False):
    RateLimitMiddleware.dispatch = _dispatch
    RateLimitMiddleware._sdm_p2_health_semantics_fix = True
