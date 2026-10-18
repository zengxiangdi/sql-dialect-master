#!/usr/bin/env python3
"""Middleware for SQL Dialect Master API.

Provides rate limiting, request-size protection, logging, and security headers.
"""
import gzip
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
from starlette.concurrency import run_in_threadpool

from backend.core.exceptions import ErrorCode

from .client_identity import resolve_client_ip
from .rate_limit_store import InMemoryRateLimitStore, RateLimitStore, create_rate_limit_store
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
    window_start: float = field(default_factory=time.monotonic)


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

    def __init__(self, app, limiter: RateLimiter = None, enabled: bool = True, max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES, trusted_proxies: tuple = ()):
        super().__init__(app)
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.limiter = limiter or RateLimiter(store=None if enabled else InMemoryRateLimitStore())
        self.enabled = enabled
        self.max_body_bytes = max_body_bytes
        self.trusted_proxies = trusted_proxies

    async def _read_bounded_body(self, request: Request) -> Response | None:
        """Consume and cache request bodies without trusting Content-Length."""
        # HEAD has no response body by definition and some ASGI servers do
        # not expose a request stream for it.  GET bodies are unusual but
        # still need the same bound so an oversized payload cannot bypass
        # request-size protection by changing the HTTP method.
        if request.method == "HEAD":
            return None
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse(status_code=400, content={"success": False, "error": {"code": 400, "message": "Invalid Content-Length"}, "timestamp": datetime.now().isoformat()})
            if declared_length < 0:
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
        is_health_probe = (
            request.url.path in {"/health", "/", "/ready", "/health/deep"}
            and request.method in {"GET", "HEAD"}
        )
        # Browser CORS preflight requests carry no business payload and are
        # generated automatically before the actual API call.  Counting them
        # against the application rate limit can make an otherwise healthy
        # client fail before it reaches the endpoint, especially when each
        # request uses a non-simple X-Request-ID or X-API-Key header.
        is_cors_preflight = request.method == "OPTIONS" and bool(
            request.headers.get("origin")
            and request.headers.get("access-control-request-method")
        )

        # Apply rate limiting before JSON/body parsing.  This prevents a
        # client from spending unbounded CPU on invalid payloads while still
        # keeping the request-size guard active when rate limiting is disabled.
        rate_limit_checked = False
        remaining = reset_time = None
        if self.enabled and not is_health_probe and not is_cors_preflight:
            client_id = self._get_client_id(request)
            # Redis checks use a synchronous client; a stalled store must not
            # block the event loop used by unrelated liveness/API requests.
            is_allowed, remaining, reset_time = await run_in_threadpool(self.limiter.is_allowed, client_id)
            rate_limit_checked = True
            if not is_allowed:
                logger.warning("Rate limit exceeded for client: %s", _sanitize_log_value(client_id))
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "error": {"code": 429, "message": "Rate limit exceeded", "retry_after": reset_time}, "timestamp": datetime.now().isoformat()},
                    headers={"X-RateLimit-Limit": str(self.limiter._requests_per_window), "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_time), "Retry-After": str(reset_time)},
                )

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
        if is_health_probe:
            if request.url.path in {"/ready", "/health/deep"}:
                return await health_probe_response(request)
            return await call_next(request)
        response = await call_next(request)
        if rate_limit_checked:
            response.headers["X-RateLimit-Limit"] = str(self.limiter._requests_per_window)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_time)
        return response

    def _get_client_id(self, request: Request) -> str:
        return resolve_client_ip(request, self.trusted_proxies)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Structured request logging and request-id propagation."""

    def __init__(self, app, log_body: bool = False, trusted_proxies: tuple = ()):
        super().__init__(app)
        self.log_body = log_body
        self.trusted_proxies = trusted_proxies

    @staticmethod
    def _get_request_id(request: Request) -> str:
        """Reuse a valid request ID; otherwise issue a fresh UUID.

        The React client prefixes UUIDs with ``web-`` to identify browser
        traffic.  Keep accepting the prefix while still validating the UUID
        payload so arbitrary header values cannot be copied into logs or
        response headers.
        """
        candidate = request.headers.get("X-Request-ID")
        if candidate:
            uuid_candidate = candidate.removeprefix("web-")
            try:
                parsed = uuid.UUID(uuid_candidate)
                if parsed.variant == uuid.RFC_4122:
                    return candidate
            except (ValueError, AttributeError, TypeError):
                pass
        return str(uuid.uuid4())

    @staticmethod
    async def _normalize_error_response(response: Response, request_id: str) -> Response:
        """Normalize standard HTTP 4xx JSON responses while preserving domain-specific codes."""
        code_by_status = {
            400: ErrorCode.BAD_REQUEST.value,
            401: ErrorCode.UNAUTHORIZED.value,
            404: ErrorCode.NOT_FOUND.value,
            405: ErrorCode.METHOD_NOT_ALLOWED.value,
            413: ErrorCode.PAYLOAD_TOO_LARGE.value,
            422: ErrorCode.VALIDATION_FAILED.value,
            429: ErrorCode.RATE_LIMITED.value,
            503: ErrorCode.SERVICE_UNAVAILABLE.value,
            504: ErrorCode.REQUEST_TIMEOUT.value,
        }
        if response.status_code not in code_by_status:
            return response
        if "json" not in response.headers.get("content-type", "").lower():
            return response

        # BaseHTTPMiddleware often returns a streaming response even when the
        # endpoint produced JSON.  Buffer that stream exactly once for
        # normalization, but replay the original bytes when the payload is
        # malformed so an error response is never silently emptied.
        encoded_with_gzip = "gzip" in response.headers.get("content-encoding", "").lower()
        streamed_body = not hasattr(response, "body")
        raw_body = b""
        try:
            if hasattr(response, "body"):
                raw_body = response.body
            else:
                chunks = []
                async for chunk in response.body_iterator:
                    chunks.append(chunk)
                raw_body = b"".join(chunks)
            # GZipMiddleware is inside this middleware.  Error responses over
            # its threshold therefore arrive compressed; decode them before
            # applying the stable JSON envelope so large and small errors have
            # identical browser-visible contracts.
            if encoded_with_gzip:
                raw_body = gzip.decompress(raw_body)
        except (AttributeError, TypeError):
            return response
        except (OSError, EOFError):
            # A malformed compressed stream must remain observable to the
            # caller.  If it was buffered from a streaming response, replay
            # the original bytes instead of returning an already-consumed
            # iterator.
            if not streamed_body:
                return response
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return Response(
                content=raw_body,
                status_code=response.status_code,
                headers=headers,
                background=response.background,
            )
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError, OSError):
            if hasattr(response, "body"):
                return response
            headers = dict(response.headers)
            headers.pop("content-length", None)
            if encoded_with_gzip:
                headers.pop("content-encoding", None)
            return Response(
                content=raw_body,
                status_code=response.status_code,
                headers=headers,
                background=response.background,
            )

        if response.status_code == 503 and isinstance(payload, dict) and "checks" in payload:
            # Readiness has a public diagnostics schema of its own. Preserve
            # status/checks when the service is unhealthy, including after
            # consuming the downstream streaming response to decode JSON.
            headers = dict(response.headers)
            headers.pop("content-length", None)
            headers.pop("content-type", None)
            headers.pop("content-encoding", None)
            payload.setdefault("request_id", request_id)
            return JSONResponse(status_code=503, content=payload, headers=headers)

        error = payload.get("error") if isinstance(payload, dict) else None
        expected_code = code_by_status[response.status_code]
        if not isinstance(error, dict):
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if response.status_code == 422:
                error = {
                    "code": expected_code,
                    "message": "Request validation failed",
                    "details": detail if isinstance(detail, list) else ([detail] if detail else []),
                }
            elif response.status_code == 413:
                error = {
                    "code": expected_code,
                    "message": str(detail or "Request body exceeds the maximum allowed size"),
                    "details": {},
                }
            elif response.status_code == 429:
                error = {
                    "code": expected_code,
                    "message": str(detail or "Rate limit exceeded"),
                    "details": {},
                }
            elif response.status_code == 405:
                error = {
                    "code": expected_code,
                    "message": str(detail or "Method not allowed"),
                    "details": {},
                }
            else:
                error = {
                    "code": expected_code,
                    "message": str(detail or ("Resource not found" if response.status_code == 404 else "Bad request")),
                    "details": {},
                }
        else:
            code = error.get("code")
            if not isinstance(code, str):
                error["code"] = expected_code
            error.setdefault("details", {})

        normalized = {
            "success": False,
            "error": error,
            "timestamp": payload.get("timestamp", datetime.now().isoformat()) if isinstance(payload, dict) else datetime.now().isoformat(),
            "request_id": request_id,
        }
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("content-type", None)
        headers.pop("content-encoding", None)
        return JSONResponse(status_code=response.status_code, content=normalized, headers=headers)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Request duration is an elapsed interval, so use a monotonic clock.
        # ``time.time()`` may move backwards/forwards during a wall-clock
        # correction and corrupt both logs and latency metrics.
        start_time = time.perf_counter()
        request_id = self._get_request_id(request)
        request.state.request_id = request_id
        status_code = 500
        error = None
        log_data = {"event": "request_start", "request_id": request_id, "method": _sanitize_log_value(request.method), "path": _sanitize_log_value(request.url.path), "query": _sanitize_log_value(str(request.query_params)), "client": _sanitize_log_value(resolve_client_ip(request, self.trusted_proxies)), "timestamp": datetime.now().isoformat()}
        logger.info(json.dumps(log_data))
        try:
            response = await call_next(request)
            response = await self._normalize_error_response(response, request_id)
            status_code = response.status_code
        except Exception as exc:
            error = _sanitize_log_value(str(exc))
            raise
        finally:
            process_time = time.perf_counter() - start_time
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
