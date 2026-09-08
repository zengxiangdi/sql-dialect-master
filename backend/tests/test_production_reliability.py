"""Regression tests for production reliability hardening."""

import sys
import types

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, transpiler
from backend.api.middleware import RateLimiter
from backend.api.rate_limit_store import InMemoryRateLimitStore, RedisRateLimitStore, create_rate_limit_store


def test_memory_store_enforces_limit():
    limiter = RateLimiter(requests_per_window=2, window_seconds=60, store=InMemoryRateLimitStore())
    assert limiter.is_allowed("client")[0] is True
    assert limiter.is_allowed("client")[0] is True
    assert limiter.is_allowed("client")[0] is False


def test_memory_store_prunes_expired_entries(monkeypatch):
    store = InMemoryRateLimitStore()
    clock = iter([100.0, 100.0, 161.0])
    monkeypatch.setattr("backend.api.rate_limit_store.time.time", lambda: next(clock))
    store.check("old-client", 10, 60)
    assert store.stats()["active_clients"] == 1
    store.check("new-client", 10, 60)
    assert store.stats()["active_clients"] == 1


def test_rate_limit_store_selection(monkeypatch):
    monkeypatch.setenv("SDM_RATE_LIMIT_BACKEND", "memory")
    store = create_rate_limit_store()
    assert isinstance(store, InMemoryRateLimitStore)

    monkeypatch.setenv("SDM_RATE_LIMIT_BACKEND", "unknown")
    with pytest.raises(ValueError, match="expected 'memory' or 'redis'"):
        create_rate_limit_store()


def test_redis_store_uses_atomic_script(monkeypatch):
    class FakeClient:
        def register_script(self, script):
            self.script = script
            assert "INCR" in script
            assert "EXPIRE" in script

            def invoke(*, keys, args):
                assert keys == ["sdm:rate-limit:client"]
                assert args == [60]
                return [2, 59]

            return invoke

    fake_redis = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *args, **kwargs: FakeClient())
    )
    monkeypatch.setitem(sys.modules, "redis", fake_redis)

    store = RedisRateLimitStore("redis://localhost/0")
    allowed, remaining, reset = store.check("client", 3, 60)
    assert allowed is True
    assert remaining == 1
    assert reset == 59


def test_redis_backend_requires_url(monkeypatch):
    monkeypatch.setenv("SDM_RATE_LIMIT_BACKEND", "redis")
    monkeypatch.delenv("SDM_REDIS_URL", raising=False)
    with pytest.raises(ValueError, match="Redis URL is required"):
        create_rate_limit_store()


def test_liveness_endpoint_stays_lightweight():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["probe"] == "liveness"


def test_readiness_endpoint_runs_component_checks():
    response = TestClient(app).get("/ready")
    assert response.status_code in {200, 503}
    payload = response.json()
    assert payload["probe"] == "readiness"
    assert set(payload["checks"]) == {"transpiler", "functions", "types", "nl2sql"}


def test_readiness_bypasses_rate_limit(monkeypatch):
    limiter = app.user_middleware[0].kwargs.get("limiter") if app.user_middleware else None
    if limiter is None:
        pytest.skip("Application middleware order is implementation-dependent")
    limiter._requests_per_window = 1
    client = TestClient(app)
    first = client.get("/ready")
    second = client.get("/ready")
    assert first.status_code in {200, 503}
    assert second.status_code in {200, 503}


def test_stats_uses_actual_rule_count():
    response = TestClient(app).get("/api/stats")
    assert response.status_code == 200
    assert response.json()["stats"]["overview"]["conversion_rules"] == len(
        transpiler.post_processor.engine.rules
    )
