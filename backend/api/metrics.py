"""Protected Prometheus metrics for the API process."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import Request
from fastapi.responses import PlainTextResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from backend.core.config import settings
from backend.core.metadata import PROJECT_VERSION

REGISTRY = CollectorRegistry(auto_describe=True)

BUILD_INFO = Gauge("sdm_build_info", "SQL Dialect Master build information", ["version"], registry=REGISTRY)
BUILD_INFO.labels(version=PROJECT_VERSION).set(1)

HTTP_REQUESTS = Counter(
    "sdm_http_requests_total",
    "HTTP requests handled by the API",
    ["method", "route", "status_class"],
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "sdm_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route", "status_class"],
    registry=REGISTRY,
)
RATE_LIMIT_REJECTIONS = Counter(
    "sdm_rate_limit_rejections_total",
    "Rate-limited requests",
    registry=REGISTRY,
)
TRANSPILE_REQUESTS = Counter(
    "sdm_transpile_requests_total",
    "Conversion requests by dialect pair and result",
    ["source", "target", "result"],
    registry=REGISTRY,
)
TRANSPILE_BATCH_REQUESTS = Counter(
    "sdm_transpile_batch_requests_total",
    "Batch conversion handler outcomes by dialect pair and result",
    ["source", "target", "result"],
    registry=REGISTRY,
)
TRANSPILE_BATCH_ITEMS = Counter(
    "sdm_transpile_batch_items_total",
    "Items in complete batch results received by the API handler",
    ["source", "target", "result"],
    registry=REGISTRY,
)
TRANSPILE_BATCH_SIZE = Histogram(
    "sdm_transpile_batch_size",
    "Statement count of validated batches before worker admission",
    buckets=(1, 2, 5, 10, 20, 50, 100),
    registry=REGISTRY,
)

_transpiler_provider: Callable[[], object] | None = None
_worker_provider: Callable[[], object] | None = None
_limiter_provider: Callable[[], object] | None = None


def configure_runtime_metrics(*, transpiler_provider=None, worker_provider=None, limiter_provider=None) -> None:
    """Register process-local runtime providers used when /metrics is scraped."""
    global _transpiler_provider, _worker_provider, _limiter_provider
    _transpiler_provider = transpiler_provider
    _worker_provider = worker_provider
    _limiter_provider = limiter_provider


class RuntimeCollector:
    """Read low-frequency runtime snapshots without copying them per request."""

    def collect(self):
        if _transpiler_provider is not None:
            try:
                stats = _transpiler_provider().get_stats()
                cache = stats.get("cache", {})
                if cache.get("enabled", True) is not False:
                    yield CounterMetricFamily("sdm_transpile_cache_hits_total", "Transpiler cache hits", value=cache.get("hits", 0))
                    yield CounterMetricFamily("sdm_transpile_cache_misses_total", "Transpiler cache misses", value=cache.get("misses", 0))
                    yield CounterMetricFamily("sdm_transpile_cache_evictions_total", "Transpiler cache evictions", value=cache.get("evictions", 0))
                    yield GaugeMetricFamily("sdm_transpile_cache_size", "Current transpiler cache size", value=cache.get("size", 0))
            except Exception:
                pass

        if _worker_provider is not None:
            try:
                stats = _worker_provider().stats()
                yield GaugeMetricFamily("sdm_api_worker_capacity", "API worker pool capacity", value=stats["capacity"])
                yield GaugeMetricFamily("sdm_api_worker_in_use", "API worker slots in use", value=stats["in_use"])
                yield CounterMetricFamily("sdm_api_worker_rejections_total", "API worker capacity rejections", value=stats["rejections"])
                yield CounterMetricFamily("sdm_api_request_timeouts_total", "API request timeouts", value=stats["timeouts"])
            except Exception:
                pass

        if _limiter_provider is not None:
            try:
                stats = _limiter_provider().get_stats()
                if stats.get("backend") == "memory":
                    yield GaugeMetricFamily("sdm_rate_limit_active_clients", "Active in-memory rate-limit clients", value=stats.get("active_clients", 0))
            except Exception:
                pass


REGISTRY.register(RuntimeCollector())


def normalize_method(method: str) -> str:
    return method if method in {"GET", "POST", "HEAD", "OPTIONS"} else "other"


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    return template if template else "other"


def status_class(status_code: int) -> str:
    return f"{status_code // 100}xx" if 100 <= status_code < 600 else "other"


def record_http_request(request: Request, status_code: int, duration: float) -> None:
    if request.url.path == "/metrics":
        return
    labels = (normalize_method(request.method), route_template(request), status_class(status_code))
    HTTP_REQUESTS.labels(*labels).inc()
    HTTP_DURATION.labels(*labels).observe(duration)


def record_rate_limit_rejection() -> None:
    RATE_LIMIT_REJECTIONS.inc()


def record_transpile_request(source: str, target: str, result: str) -> None:
    TRANSPILE_REQUESTS.labels(source=source, target=target, result=result).inc()


def record_transpile_batch_request(source: str, target: str, result: str) -> None:
    TRANSPILE_BATCH_REQUESTS.labels(source=source, target=target, result=result).inc()


def record_transpile_batch_items(source: str, target: str, succeeded: int, failed: int) -> None:
    if succeeded:
        TRANSPILE_BATCH_ITEMS.labels(source=source, target=target, result="success").inc(succeeded)
    if failed:
        TRANSPILE_BATCH_ITEMS.labels(source=source, target=target, result="error").inc(failed)


def observe_transpile_batch_size(size: int) -> None:
    TRANSPILE_BATCH_SIZE.observe(size)


def _authorized(request: Request) -> bool:
    configured = settings.metrics_token
    expected = configured.get_secret_value().strip() if configured else ""
    supplied = request.headers.get("X-Metrics-Token", "")
    return bool(expected and supplied and secrets.compare_digest(supplied, expected))


async def metrics_response(request: Request) -> Response:
    if not settings.metrics_enabled:
        return Response(status_code=404)
    if not _authorized(request):
        return Response(status_code=401, content="Metrics token required")
    return PlainTextResponse(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


class MetricsMiddleware:
    """ASGI middleware that records final HTTP status and elapsed time."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        import time

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        await self.app(scope, receive, send_wrapper)
        request = Request(scope)
        record_http_request(request, status_code, time.perf_counter() - started)
