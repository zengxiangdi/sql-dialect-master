import sys
import types

import pytest

from backend.api.rate_limit_store import (
    InMemoryRateLimitStore,
    RedisRateLimitStore,
    create_rate_limit_store,
)


def test_memory_store_enforces_limit_and_cleans_up():
    store = InMemoryRateLimitStore()
    clock = iter([100.0, 100.0, 161.0])
    original_time = sys.modules["backend.api.rate_limit_store"].time.time
    sys.modules["backend.api.rate_limit_store"].time.time = lambda: next(clock)
    try:
        assert store.check("old", 1, 60)[0] is True
        assert store.stats()["active_clients"] == 1
        assert store.check("new", 1, 60)[0] is True
        assert store.stats()["active_clients"] == 1
    finally:
        sys.modules["backend.api.rate_limit_store"].time.time = original_time


def test_store_selection(monkeypatch):
    monkeypatch.setenv("SDM_RATE_LIMIT_BACKEND", "memory")
    assert isinstance(create_rate_limit_store(), InMemoryRateLimitStore)
    monkeypatch.setenv("SDM_RATE_LIMIT_BACKEND", "invalid")
    with pytest.raises(ValueError, match="expected 'memory' or 'redis'"):
        create_rate_limit_store()


def test_redis_store_is_atomic_and_checks_connectivity(monkeypatch):
    class FakeClient:
        def ping(self):
            return True

        def register_script(self, script):
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
    assert (allowed, remaining, reset) == (True, 1, 59)


def test_redis_store_fails_fast_when_unreachable(monkeypatch):
    class FakeClient:
        def ping(self):
            raise ConnectionError("refused")

    fake_redis = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *args, **kwargs: FakeClient())
    )
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    with pytest.raises(ConnectionError, match="refused"):
        RedisRateLimitStore("redis://localhost/0")


def test_redis_store_requires_url(monkeypatch):
    monkeypatch.setenv("SDM_RATE_LIMIT_BACKEND", "redis")
    monkeypatch.delenv("SDM_REDIS_URL", raising=False)
    with pytest.raises(ValueError, match="Redis URL is required"):
        create_rate_limit_store()
