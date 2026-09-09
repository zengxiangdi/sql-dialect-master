import json
import logging
import time
import uuid
from datetime import datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


def _sanitize_log_value(value: str, max_length: int = 500) -> str:
    """Prevent control characters from forging or corrupting log records."""
    return value.replace("\r", "\\r").replace("\n", "\\n")[:max_length]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request lifecycle events with bounded, sanitized fields."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        request_id = str(uuid.uuid4())
        status_code = 500
        error = None
        log_data = {
            "event": "request_start",
            "request_id": request_id,
            "method": _sanitize_log_value(request.method),
            "path": _sanitize_log_value(request.url.path),
            "query": _sanitize_log_value(str(request.query_params)),
            "client": _sanitize_log_value(request.client.host if request.client else "unknown"),
            "timestamp": datetime.now().isoformat(),
        }
        logger.info(json.dumps(log_data))
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error = _sanitize_log_value(str(exc))
            raise
        finally:
            process_time = time.time() - start_time
            log_data = {
                "event": "request_end",
                "request_id": request_id,
                "method": _sanitize_log_value(request.method),
                "path": _sanitize_log_value(request.url.path),
                "status_code": status_code,
                "process_time_ms": round(process_time * 1000, 2),
                "error": error,
                "timestamp": datetime.now().isoformat(),
            }
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
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response
