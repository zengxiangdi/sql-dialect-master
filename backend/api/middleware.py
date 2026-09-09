#!/usr/bin/env python3
"""Middleware for SQL Dialect Master API.

Provides rate limiting, request-size protection, structured logging, and security headers.
"""
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .rate_limit_store import RateLimitStore, create_rate_limit_store
from .readiness import deep_health_response, readiness_response

logger = logging.getLogger(__name__)
DEFAULT_MAX_REQUEST_BODY_BYTES = 512 * 1024
_SAFE_COLUMN_HINT = re.compile(
    r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*"
)


@dataclass
class RateLimitEntry:
    """Legacy compatibility entry."""
    requests: int = 0
    window_start: float = field(default_factory=lambda: time.time())


class RateLimiter:
    """Rate limiter backed by a local or shared store."""

    def __init__(
        self,
        requests_per_window: int = 100,
        window_seconds: int = 60,
        store: RateLimitStore = None,
    ):
        if requests_per_window <= 0:
            raise ValueError("requests_per_window must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._requests_per_window = requests_per_window
        self._window_seconds = window_seconds
        self._store = store or create_rate_limit_store()

    @property
    def _limits(self):
        """Read-only compatibility view for the in-memory backend."""
        return getattr(self._store, "_entries", {})

    def is_allowed(self, client_id: str) -> tuple:
        return self._store.check(
            client_id, self._requests_per_window, self._window_seconds
        )

    def get_stats(self) -> Dict:
        stats = self._store.stats()
        stats.update(
            {
                "requests_per_window": self._requests_per_window,
                "window_seconds": self._window_seconds,
            }
        )
        return stats


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Generate a request ID and paired structured start/end logs."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        status_code = 500
        error = None
        logger.info(
            json.dumps(
                {
                    "event": "request_start",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.query_params),
                    "client": request.client.host if request.client else "unknown",
                    "timestamp": datetime.now().isoformat(),
                }
            )
        )
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            logger.log(
                logging.WARNING if status_code >= 400 else logging.INFO,
                json.dumps(
                    {
                        "event": "request_end",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "process_time_ms": round(
                            (time.time() - start_time) * 1000, 2
                        ),
                        "error": error,
                        "timestamp": datetime.now().isoformat(),
                    }
                ),
            )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting and request guard middleware."""

    def __init__(
        self,
        app,
        limiter: RateLimiter = None,
        enabled: bool = True,
        max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES,
    ):
        super().__init__(app)
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.limiter = limiter or RateLimiter()
        self.enabled = enabled
        self.max_body_bytes = max_body_bytes
        self._structured_logging = StructuredLoggingMiddleware(app)

    async def _read_bounded_body(self, request: Request) -> Response | None:
        """Consume and cache request bodies without trusting Content-Length."""
        if request.method in {"GET", "HEAD"}:
            return None
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": {
                            "code": 400,
                            "message": "Invalid Content-Length",
                        },
                        "timestamp": datetime.now().isoformat(),
                    },
                )
            if declared_length > self.max_body_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "success": False,
                        "error": {
                            "code": 413,
                            "message": "Request body exceeds the maximum allowed size",
                            "max_bytes": self.max_body_bytes,
                        },
                        "timestamp": datetime.now().isoformat(),
                    },
                )

        total = 0
        chunks = []
        async for chunk in request.stream():
            total += len(chunk)
            if total > self.max_body_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "success": False,
                        "error": {
                            "code": 413,
                            "message": "Request body exceeds the maximum allowed size",
                            "max_bytes": self.max_body_bytes,
                        },
                        "timestamp": datetime.now().isoformat(),
                    },
                )
            chunks.append(chunk)
        request._body = b"".join(chunks)
        return None

    async def _validate_column_hints(self, request: Request) -> Response | None:
        if request.method != "POST" or request.url.path != "/api/nl2sql":
            return None
        try:
            payload = json.loads(request._body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or "column_hints" not in payload:
            return None

        hints = payload["column_hints"]
        if not isinstance(hints, list) or not 1 <= len(hints) <= 32:
            return JSONResponse(
                status_code=422,
                content={
                    "success": False,
                    "error": {
                        "code": 422,
                        "message": "column_hints must contain 1 to 32 SQL identifiers",
                    },
                    "timestamp": datetime.now().isoformat(),
                },
            )
        for hint in hints:
            if not isinstance(hint, str) or not _SAFE_COLUMN_HINT.fullmatch(hint.strip()):
                return JSONResponse(
                    status_code=422,
                    content={
                        "success": False,
                        "error": {
                            "code": 422,
                            "message": "column_hints entries must be simple identifiers or dotted identifiers",
                        },
                        "timestamp": datetime.now().isoformat(),
                    },
                )
        return None

    async def _dispatch_inner(self, request: Request, call_next) -> Response:
        body_error = await self._read_bounded_body(request)
        if body_error is not None:
            return body_error
        if request.url.path == "/health" and request.method in {"GET", "HEAD"}:
            return JSONResponse(
                status_code=200,
                headers={"Cache-Control": "no-store"},
                content={
                    "status": "healthy",
                    "probe": "liveness",
                    "uptime": "Available",
                    "services": {
                        "transpiler": {"status": "✅ healthy"},
                        "functions": {"status": "✅ healthy"},
                        "types": {"status": "✅ healthy"},
                        "nl2sql": {"status": "✅ healthy"},
                    },
                    "timestamp": datetime.now().isoformat(),
                },
            )
        if request.url.path == "/ready" and request.method in {"GET", "HEAD"}:
            return await readiness_response(request)
        if request.url.path == "/health/deep" and request.method in {"GET", "HEAD"}:
            return await deep_health_response(request)

        column_error = await self._validate_column_hints(request)
        if column_error is not None:
            return column_error
        if not self.enabled:
            return await call_next(request)
        if request.url.path == "/" and request.method in {"GET", "HEAD"}:
            return await call_next(request)

        client_id = self._get_client_id(request)
        is_allowed, remaining, reset_time = self.limiter.is_allowed(client_id)
        if not is_allowed:
            logger.warning("Rate limit exceeded for client: %s", client_id)
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": {
                        "code": 429,
                        "message": "Rate limit exceeded",
                        "retry_after": reset_time,
                    },
                    "timestamp": datetime.now().isoformat(),
                },
                headers={
                    "X-RateLimit-Limit": str(self.limiter._requests_per_window),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_time),
                    "Retry-After": str(reset_time),
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limiter._requests_per_window)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_time)
        return response

    async def dispatch(self, request: Request, call_next) -> Response:
        return await self._structured_logging.dispatch(
            request,
            self._dispatch_inner,
        )

    def _get_client_id(self, request: Request) -> str:
        return request.client.host if request.client else "unknown"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
