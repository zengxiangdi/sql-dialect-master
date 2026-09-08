#!/usr/bin/env python3
"""Middleware for SQL Dialect Master API.

Provides rate limiting, request-size protection, logging, and security headers.
"""
import logging
import time
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .rate_limit_store import RateLimitStore, create_rate_limit_store

logger = logging.getLogger(__name__)
DEFAULT_MAX_REQUEST_BODY_BYTES = 512 * 1024


@dataclass
class RateLimitEntry:
    """Legacy compatibility entry for callers that inspect rate-limit state."""
    requests: int = 0
    window_start: float = field(default_factory=lambda: time.time())


class RateLimiter:
    """Rate limiter backed by a local or shared store."""

    def __init__(self, requests_per_window: int = 100, window_seconds: int = 60, store: RateLimitStore = None):
        if requests_per_window <= 0:
            raise ValueError("requests_per_window must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._requests_per_window = requests_per_window
        self._window_seconds = window_seconds
        self._store = store or create_rate_limit_store()

    @property
    def _limits(self):
        """Read-only compatibility view for the legacy in-memory implementation."""
        return getattr(self._store, "_entries", {})

    def is_allowed(self, client_id: str) -> tuple:
        """Check and consume one request from the configured store."""
        return self._store.check(client_id, self._requests_per_window, self._window_seconds)

    def get_stats(self) -> Dict:
        """Get rate limiter configuration and store metadata."""
        stats = self._store.stats()
        stats.update({"requests_per_window": self._requests_per_window, "window_seconds": self._window_seconds})
        return stats


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with an early request-body size guard."""

    def __init__(self, app, limiter: RateLimiter = None, enabled: bool = True, max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES):
        super().__init__(app)
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.limiter = limiter or RateLimiter()
        self.enabled = enabled
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in {"GET", "HEAD"}:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError:
                    return JSONResponse(status_code=400, content={"success": False, "error": {"code": 400, "message": "Invalid Content-Length"}, "timestamp": datetime.now().isoformat()})
                if declared_length > self.max_body_bytes:
                    return JSONResponse(status_code=413, content={"success": False, "error": {"code": 413, "message": "Request body exceeds the maximum allowed size", "max_bytes": self.max_body_bytes}, "timestamp": datetime.now().isoformat()})

        if not self.enabled:
            return await call_next(request)
        if request.url.path in ["/health", "/health/deep", "/ready", "/"] and request.method in {"GET", "HEAD"}:
            return await call_next(request)

        client_id = self._get_client_id(request)
        is_allowed, remaining, reset_time = self.limiter.is_allowed(client_id)
        if not is_allowed:
            logger.warning(f"Rate limit exceeded for client: {client_id}")
            return JSONResponse(
                status_code=429,
                content={"success": False, "error": {"code": 429, "message": "Rate limit exceeded", "retry_after": reset_time}, "timestamp": datetime.now().isoformat()},
                headers={"X-RateLimit-Limit": str(self.limiter._requests_per_window), "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_time), "Retry-After": str(reset_time)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limiter._requests_per_window)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_time)
        return response

    def _get_client_id(self, request: Request) -> str:
        """Extract client identifier from request without trusting forwarded headers."""
        return request.client.host if request.client else "unknown"


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Structured logging middleware for API requests."""

    def __init__(self, app, log_body: bool = False):
        super().__init__(app)
        self.log_body = log_body

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        request_id = str(uuid.uuid4())
        log_data = {"event": "request_start", "request_id": request_id, "method": request.method, "path": request.url.path, "query": str(request.query_params), "client": request.client.host if request.client else "unknown", "timestamp": datetime.now().isoformat()}
        logger.info(json.dumps(log_data))
        try:
            response = await call_next(request)
            status_code = response.status_code
            error = None
        except Exception as e:
            status_code = 500
            error = str(e)
            raise
        finally:
            process_time = time.time() - start_time
            log_data = {"event": "request_end", "request_id": request_id, "method": request.method, "path": request.url.path, "status_code": status_code, "process_time_ms": round(process_time * 1000, 2), "error": error, "timestamp": datetime.now().isoformat()}
            (logger.warning if status_code >= 400 else logger.info)(json.dumps(log_data))
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
