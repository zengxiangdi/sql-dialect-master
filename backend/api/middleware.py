#!/usr/bin/env python3
"""Middleware for SQL Dialect Master API.

Provides rate limiting, request-size protection, logging, and security headers.
"""
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.exceptions import ErrorCode

from .rate_limit_store import RateLimitStore, create_rate_limit_store
from .readiness import health_probe_response

logger = logging.getLogger(__name__)
DEFAULT_MAX_REQUEST_BODY_BYTES = 512 * 1024


def _sanitize_log_value(value: str, max_length: int = 500) -> str:
    """Prevent control characters from forging or corrupting log records."""
    return value.replace("\r", "\\r").replace("\n", "\\n")[:max_length]


@dataclass
class RateLimitEntry:
    """Legacy compatibility entry."""
    requests: int = 0
    window_start: float = field(default_factory=time.time)


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
        """Read-only compatibility view for the in-memory backend."""
        return getattr(self._store, "_entries", {})

    def is_allowed(self, client_id: str) -> tuple:
        return self._store.check(client_id, self._requests_per_window, self._window_seconds)

    def get_stats(self) -> Dict:
        stats = self._store.stats()
        stats.update({"requests_per_window": self._requests_per_window, "window_seconds": self._window_seconds})
        return stats


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with a bounded request-body guard."""

    def __init__(self, app, limiter: RateLimiter = None, enabled: bool = True, max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES):
        super().__init__(app)
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.limiter = limiter or RateLimiter()
        self.enabled = enabled
        self.max_body_bytes = max_body_bytes

    async def _read_bounded_body(self, request: Request) -> Response | None:
        """Consume and cache request bodies without trusting Content-Length."""
        if request.method in {"GET", "HEAD"}:
            return None
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse(status_code=400, content={"success": False, "error": {"code": 400, "message": "Invalid Content-Length"}, "timestamp": datetime.now().isoformat()})
            if declared_length > self.max_body_bytes:
                return JSONResponse(status_code=413, content={"success": False, "error": {"code": 413, "message": "Request body exceeds the maximum allowed size", "max_bytes": self.max_body_bytes}, "timestamp": datetime.now().isoformat()})

        total = 0
        chunks = []
        async for chunk in request.stream():
            total += len(chunk)
            if total > self.max_body_bytes:
                return JSONResponse(status_code=413, content={"success": False, "error": {"code": 413, "message": "Request body exceeds the maximum allowed size", "max_bytes": self.max_body_bytes}, "timestamp": datetime.now().isoformat()})
            chunks.append(chunk)
        request._body = b"".join(chunks)
        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        body_error = await self._read_bounded_body(request)
        if body_error is not None:
            return body_error

        if request.url.path == "/api/nl2sql" and request.method == "POST":
            try:
                body = await request.body()
                payload = json.loads(body.decode("utf-8")) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                from backend.core.column_hint_validation import validate_column_hints
                error = validate_column_hints(payload.get("column_hints"))
                if error:
                    return JSONResponse(
                        status_code=422,
                        content={"success": False, "error": {"code": "VALIDATION_FAILED", "message": error}},
                    )

        if not self.enabled:
            return await call_next(request)
        if request.url.path in {"/health", "/", "/ready", "/health/deep"} and request.method in {"GET", "HEAD"}:
            if request.url.path in {"/ready", "/health/deep"}:
                return await health_probe_response(request)
            return await call_next(request)

        client_id = self._get_client_id(request)
        is_allowed, remaining, reset_time = self.limiter.is_allowed(client_id)
        if not is_allowed:
            logger.warning("Rate limit exceeded for client: %s", _sanitize_log_value(client_id))
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
        return request.client.host if request.client else "unknown"


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Structured request logging and request-id propagation."""

    def __init__(self, app, log_body: bool = False):
        super().__init__(app)
        self.log_body = log_body

    @staticmethod
    def _get_request_id(request: Request) -> str:
        """Reuse a valid RFC 4122 request ID; otherwise issue a fresh UUID."""
        candidate = request.headers.get("X-Request-ID")
        if candidate:
            try:
                parsed = uuid.UUID(candidate)
                if parsed.variant == uuid.RFC_4122:
                    return candidate
            except (ValueError, AttributeError, TypeError):
                pass
        return str(uuid.uuid4())

    @staticmethod
    def _normalize_error_response(response: Response, request_id: str) -> Response:
        """Normalize generic 4xx JSON responses without replacing domain-specific codes."""
        if not isinstance(response, JSONResponse) or response.status_code not in {400, 404, 422}:
            return response

        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            return response

        error = payload.get("error")
        if not isinstance(error, dict):
            detail = payload.get("detail")
            if response.status_code == 422:
                error = {
                    "code": ErrorCode.VALIDATION_FAILED.value,
                    "message": "Request validation failed",
                    "details": detail if isinstance(detail, list) else ([detail] if detail else []),
                }
            elif response.status_code == 404:
                error = {
                    "code": ErrorCode.NOT_FOUND.value,
                    "message": str(detail or "Resource not found"),
                    "details": {},
                }
            else:
                error = {
                    "code": ErrorCode.BAD_REQUEST.value,
                    "message": str(detail or "Bad request"),
                    "details": {},
                }
        else:
            code = error.get("code")
            if response.status_code == 404 and not isinstance(code, str):
                error["code"] = ErrorCode.NOT_FOUND.value
            elif response.status_code == 400 and not isinstance(code, str):
                error["code"] = ErrorCode.BAD_REQUEST.value
            elif response.status_code == 422 and not isinstance(code, str):
                error["code"] = ErrorCode.VALIDATION_FAILED.value
            error.setdefault("details", {})

        payload = {
            "success": False,
            "error": error,
            "timestamp": payload.get("timestamp", datetime.now().isoformat()),
            "request_id": request_id,
        }
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return JSONResponse(status_code=response.status_code, content=payload, headers=headers)

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        request_id = self._get_request_id(request)
        request.state.request_id = request_id
        status_code = 500
        error = None
        log_data = {"event": "request_start", "request_id": request_id, "method": _sanitize_log_value(request.method), "path": _sanitize_log_value(request.url.path), "query": _sanitize_log_value(str(request.query_params)), "client": _sanitize_log_value(request.client.host if request.client else "unknown"), "timestamp": datetime.now().isoformat()}
        logger.info(json.dumps(log_data))
        try:
            response = await call_next(request)
            response = self._normalize_error_response(response, request_id)
            status_code = response.status_code
        except Exception as exc:
            error = _sanitize_log_value(str(exc))
            raise
        finally:
            process_time = time.time() - start_time
            log_data = {"event": "request_end", "request_id": request_id, "method": _sanitize_log_value(request.method), "path": _sanitize_log_value(request.url.path), "status_code": status_code, "process_time_ms": round(process_time * 1000, 2), "error": error, "timestamp": datetime.now().isoformat()}
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
