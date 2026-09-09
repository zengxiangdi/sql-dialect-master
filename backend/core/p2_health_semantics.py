"""P2 health endpoint hardening adapters.

Sanitize deep-health error payloads and expose dependency failures as HTTP 503.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi.responses import JSONResponse

from backend.api.middleware import RateLimitMiddleware

logger = logging.getLogger(__name__)

_RAW_ERROR_KEYS = {"message", "detail", "exception", "traceback"}


def _redact_health_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "internal health check failure"
                if key in _RAW_ERROR_KEYS and isinstance(item, str)
                else _redact_health_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_health_payload(item) for item in value]
    return value


_ORIGINAL_RATE_LIMIT_DISPATCH = RateLimitMiddleware.dispatch


async def _harden_health_response(self, request, call_next):
    response = await _ORIGINAL_RATE_LIMIT_DISPATCH(self, request, call_next)
    if request.url.path != "/health/deep" or not response.media_type or "json" not in response.media_type:
        return response

    try:
        body = getattr(response, "body", None)
        if body is None:
            body = b"".join([chunk async for chunk in response.body_iterator])
        payload = _redact_health_payload(json.loads(body.decode("utf-8")))
        if not isinstance(payload, dict):
            return response
        status = 503 if payload.get("status") == "❌ unhealthy" else response.status_code
        return JSONResponse(
            status_code=status,
            content=payload,
            headers={key: value for key, value in response.headers.items() if key.lower() != "content-length"},
        )
    except Exception:
        logger.warning("Unable to sanitize deep health response", exc_info=True)
        return response


if not getattr(RateLimitMiddleware, "_sdm_p2_health_semantics", False):
    RateLimitMiddleware.dispatch = _harden_health_response
    RateLimitMiddleware._sdm_p2_health_semantics = True
