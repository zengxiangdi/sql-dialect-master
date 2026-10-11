"""Boundary regressions for middleware, settings, scanner and Redis setup."""

import sys
import types

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.middleware import RateLimitMiddleware, RateLimiter
from backend.api.rate_limit_store import RedisRateLimitStore
from backend.core.cache import TTLCache
from backend.core.config import AppSettings
from backend.core.p1_sql_scanner import mask_non_executable
from backend.core.transpiler import SQLTranspiler


def _body_app(*, limit: int = 100, body_limit: int = 8, include_get: bool = False) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        limiter=RateLimiter(requests_per_window=limit, window_seconds=60),
        max_body_bytes=body_limit,
        enabled=True,
    )

    @app.post("/echo")
    async def post_echo(request: Request):
        return {"size": len(await request.body())}

    if include_get:

        @app.get("/echo")
        async def get_echo(request: Request):
            return {"size": len(await request.body())}

    return app


def test_negative_content_length_is_rejected() -> None:
    response = TestClient(_body_app()).post(
        "/echo", content=b"", headers={"Content-Length": "-1"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Invalid Content-Length"


def test_rate_limit_runs_before_body_guard() -> None:
    client = TestClient(_body_app(limit=1, body_limit=2))
    first = client.post("/echo", content=b"123")
    second = client.post("/echo", content=b"123")
    assert first.status_code == 413
    assert second.status_code == 429


def test_get_request_body_is_bounded() -> None:
    response = TestClient(_body_app(body_limit=2, include_get=True)).request(
        "GET", "/echo", content=b"123"
    )
    assert response.status_code == 413


def test_health_probe_denial_has_request_id_without_logging_middleware() -> None:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, enabled=True)
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 403
    request_id = response.json()["request_id"]
    assert request_id
    assert response.headers["X-Request-ID"] == request_id


def test_parser_limit_falls_back_to_transpiler_limit() -> None:
    cfg = AppSettings(_env_file=None, transpiler_max_sql_length=1234)
    assert cfg.parser_max_sql_length == 1234


def test_log_level_is_normalized_and_validated() -> None:
    assert AppSettings(_env_file=None, log_level=" warning ").log_level == "WARNING"
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, log_level="verbose")


def test_redis_client_has_bounded_timeouts(monkeypatch) -> None:
    captured = {}

    class FakeClient:
        def ping(self):
            return True

        def register_script(self, _script):
            return lambda **_kwargs: [1, 59]

    def from_url(*args, **kwargs):
        captured.update(kwargs)
        return FakeClient()

    monkeypatch.setitem(
        sys.modules,
        "redis",
        types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=from_url)),
    )
    RedisRateLimitStore("redis://localhost/0")
    assert captured["socket_connect_timeout"] > 0
    assert captured["socket_timeout"] > 0


def test_cache_cleanup_start_is_atomic(monkeypatch) -> None:
    cache = TTLCache(max_size=2, ttl=1)
    starts = []
    original_start = __import__("threading").Thread.start

    def start(thread):
        starts.append(thread)
        # Do not launch the infinite daemon loop in this unit test.

    monkeypatch.setattr("threading.Thread.start", start)
    monkeypatch.setattr("threading.Thread.is_alive", lambda thread: thread in starts)
    first = cache.start_background_cleanup(interval=1)
    assert first in starts
    with pytest.raises(RuntimeError):
        cache.start_background_cleanup(interval=1)
    monkeypatch.setattr("threading.Thread.start", original_start)


def test_mysql_hash_comments_are_not_scanned_as_executable_sql() -> None:
    sql = "SELECT 1 # DROP TABLE users;\n"
    masked = mask_non_executable(sql, dialect="mysql")
    assert "DROP" not in masked
    assert SQLTranspiler()._validate_security(sql, "mysql")["blocked"] is False


def test_quoted_dangerous_identifiers_are_not_blocked() -> None:
    result = SQLTranspiler()._validate_security("SELECT `drop` FROM t", "mysql")
    assert result["blocked"] is False
    result = SQLTranspiler()._validate_security("SELECT `information_schema` FROM t", "mysql")
    assert result["blocked"] is False
