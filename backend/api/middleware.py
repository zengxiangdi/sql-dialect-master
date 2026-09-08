#!/usr/bin/env python3
"""Middleware for SQL Dialect Master API.

Provides rate limiting, request-size protection, logging, and security headers.
"""
import logging
import time
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Callable, Optional
from threading import Lock

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)
DEFAULT_MAX_REQUEST_BODY_BYTES = 256 * 1024


@dataclass
class RateLimitEntry:
    """Rate limit tracking entry."""
    requests: int = 0
    window_start: float = field(default_factory=lambda: time.time())


class RateLimiter:
    """In-memory rate limiter with sliding window."""

    def __init__(self, requests_per_window: int = 100, window_seconds: int = 60):
        if requests_per_window <= 0:
            raise ValueError("requests_per_window must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._limits: Dict[str, RateLimitEntry] = defaultdict(RateLimitEntry)
        self._requests_per_window = requests_per_window
        self._window_seconds = window_seconds
        self._cleanup_interval_seconds = max(1.0, float(window_seconds))
        self._last_cleanup_at = 0.0
        self._lock = Lock()

    def is_allowed(self, client_id: str) -> tuple:
        with self._lock:
            now = time.time()
            self._prune_expired(now)
            entry = self._limits[client_id]
            if now - entry.window_start >= self._window_seconds:
                entry.requests = 0
                entry.window_start = now
            remaining = self._requests_per_window - entry.requests
            reset_time = int(entry.window_start + self._window_seconds - now)
            if entry.requests >= self._requests_per_window:
                return False, 0, reset_time
            entry.requests += 1
            return True, remaining - 1, reset_time

    def _prune_expired(self, now: float) -> None:
        if now - self._last_cleanup_at < self._cleanup_interval_seconds:
            return
        expired_clients = [
            client_id
            for client_id, entry in self._limits.items()
            if now - entry.window_start >= self._window_seconds
        ]
        for client_id in expired_clients:
            del self._limits[client_id]
        self._last_cleanup_at = now

    def get_stats(self) -> Dict:
        with self._lock:
            self._prune_expired(time.time())
            return {
                "active_clients": len(self._limits),
                "requests_per_window": self._requests_per_window,
                "window_seconds": self._window_seconds,
            }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with an early request-body size guard."""

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

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path not in ["/health", "/health/deep", "/"]:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError:
                    return JSONResponse(
                        status_code=400,
                        content={"success": False, "error": {"code": 400, "message": "Invalid Content-Length"}},
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

        if not self.enabled:
            return await call_next(request)

        if request.url.path in ["/health", "/health/deep", "/"]:
            return await call_next(request)

        client_id = self._get_client_id(request)
        is_allowed, remaining, reset_time = self.limiter.is_allowed(client_id)
        if not is_allowed:
            logger.warning(f"Rate limit exceeded for client: {client_id}")
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

    def _get_client_id(self, request: Request) -> str:
        """Extract client identifier from request without trusting forwarded headers."""
        if request.client:
            return request.client.host
        return "unknown"


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Structured logging middleware for API requests."""

    def __init__(self, app, log_body: bool = False):
        super().__init__(app)
        self.log_body = log_body

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        request_id = str(uuid.uuid4())
        log_data = {
            "event": "request_start",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": str(request.query_params),
            "client": request.client.host if request.client else "unknown",
            "timestamp": datetime.now().isoformat(),
        }
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
            log_data = {
                "event": "request_end",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "process_time_ms": round(process_time * 1000, 2),
                "error": error,
                "timestamp": datetime.now().isoformat(),
            }
            if status_code >= 400:
                logger.warning(json.dumps(log_data))
            else:
                logger.info(json.dumps(log_data))
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
