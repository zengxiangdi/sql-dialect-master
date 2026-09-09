"""P2 health endpoint hardening adapters.

Keep liveness and deep-health semantics explicit: deep probes never expose raw
exception text to clients and report unhealthy dependency state with HTTP 503.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi.responses import Response

from backend.api.main import app

logger = logging.getLogger(__name__)


_RAW_ERROR_KEYS = {"message", "detail", "exception", "traceback"}


def _redact_health_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key in _RAW_ERROR_KEYS and isinstance(item, str):
                redacted[key] = "internal health check failure"
            else:
                redacted[key] = _redact_health_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_health_payload(item) for item in value]
    return value


class DeepHealthSanitizationMiddleware:
    """Sanitize deep-health error payloads and set correct HTTP status."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != "/health/deep":
            await self.app(scope, receive, send)
            return

        captured = {}
        body_chunks = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured.update(message)
                return
            if message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    body = b"".join(body_chunks)
                    try:
                        payload = json.loads(body.decode("utf-8"))
                        payload = _redact_health_payload(payload)
                        if payload.get("status") == "❌ unhealthy":
                            captured["status"] = 503
                        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                        logger.warning("Unable to sanitize deep health response body")
                    headers = [
                        (key, value)
                        for key, value in captured.get("headers", [])
                        if key.lower() != b"content-length"
                    ]
                    headers.append((b"content-length", str(len(body)).encode("ascii")))
                    captured["headers"] = headers
                    await send({
                        "type": "http.response.start",
                        "status": captured.get("status", 200),
                        "headers": headers,
                    })
                    await send({"type": "http.response.body", "body": body, "more_body": False})
                return
            await send(message)

        await self.app(scope, receive, capture_send)


if not getattr(app, "_sdm_p2_health_semantics", False):
    app.add_middleware(DeepHealthSanitizationMiddleware)
    app._sdm_p2_health_semantics = True
