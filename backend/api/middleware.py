#!/usr/bin/env python3
"""Middleware for SQL Dialect Master API.

Provides rate limiting, logging, and request processing middleware.
"""
import logging
import time
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Callable, Optional
from threading import Lock

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


@dataclass
class RateLimitEntry:
    """Rate limit tracking entry."""
    requests: int = 0
    window_start: float = field(default_factory=time.time)


class RateLimiter:
    """In-memory rate limiter with sliding window.
    
    Features:
    - Per-client rate limiting
    - Configurable requests per window
    - Thread-safe operations
    """
    
    def __init__(self, requests_per_window: int = 100, window_seconds: int = 60):
        """Initialize rate limiter.
        
        Args:
            requests_per_window: Maximum requests allowed per window
            window_seconds: Window duration in seconds
        """
        self._limits: Dict[str, RateLimitEntry] = defaultdict(RateLimitEntry)
        self._requests_per_window = requests_per_window
        self._window_seconds = window_seconds
        self._lock = Lock()
    
    def is_allowed(self, client_id: str) -> tuple:
        """Check if request is allowed.
        
        Args:
            client_id: Client identifier (IP address, API key, etc.)
            
        Returns:
            Tuple of (is_allowed, remaining_requests, reset_time)
        """
        with self._lock:
            now = time.time()
            entry = self._limits[client_id]
            
            # Reset window if expired
            if now - entry.window_start >= self._window_seconds:
                entry.requests = 0
                entry.window_start = now
            
            remaining = self._requests_per_window - entry.requests
            reset_time = int(entry.window_start + self._window_seconds - now)
            
            if entry.requests >= self._requests_per_window:
                return False, 0, reset_time
            
            entry.requests += 1
            return True, remaining - 1, reset_time
    
    def get_stats(self) -> Dict:
        """Get rate limiter statistics."""
        with self._lock:
            return {
                "active_clients": len(self._limits),
                "requests_per_window": self._requests_per_window,
                "window_seconds": self._window_seconds
            }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware for FastAPI."""
    
    def __init__(self, app, limiter: RateLimiter = None, enabled: bool = True):
        super().__init__(app)
        self.limiter = limiter or RateLimiter()
        self.enabled = enabled
    
    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled:
            return await call_next(request)
        
        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/health/deep", "/"]:
            return await call_next(request)
        
        # Get client identifier
        client_id = self._get_client_id(request)
        
        # Check rate limit
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
                        "retry_after": reset_time
                    },
                    "timestamp": datetime.now().isoformat()
                },
                headers={
                    "X-RateLimit-Limit": str(self.limiter._requests_per_window),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_time),
                    "Retry-After": str(reset_time)
                }
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.limiter._requests_per_window)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_time)
        
        return response
    
    def _get_client_id(self, request: Request) -> str:
        """Extract client identifier from request."""
        # Do not trust X-Forwarded-For here: clients can forge it to bypass
        # per-client limits. Deployments that sit behind a trusted proxy should
        # configure the ASGI server's proxy-header support instead.
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
        
        # Generate request ID
        request_id = f"{int(start_time * 1000)}"
        
        # Log request
        log_data = {
            "event": "request_start",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": str(request.query_params),
            "client": request.client.host if request.client else "unknown",
            "timestamp": datetime.now().isoformat()
        }
        logger.info(json.dumps(log_data))
        
        # Process request
        try:
            response = await call_next(request)
            status_code = response.status_code
            error = None
        except Exception as e:
            status_code = 500
            error = str(e)
            raise
        finally:
            # Log response
            process_time = time.time() - start_time
            log_data = {
                "event": "request_end",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "process_time_ms": round(process_time * 1000, 2),
                "error": error,
                "timestamp": datetime.now().isoformat()
            }
            
            if status_code >= 400:
                logger.warning(json.dumps(log_data))
            else:
                logger.info(json.dumps(log_data))
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to responses."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response
