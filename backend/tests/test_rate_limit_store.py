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
    clock = iter([100.0, 100.0, 161.0, 161.0])
    original_time = sys.modules["backend.api.rate_limit_store"].time.time
    sys.modules["backend.api.rate_limit_store"].time.time = lambda: next(clock)
    try:
        assert store.check("old", 1, 60)[0] is True
        assert store.stats()["active_clients"] == 1
        assert store.check("new", 1, 60)[0] is True
        assert store.stats()["active_clients"] == 1
    finally:
        sys.modules["backend.api.rate_limit_store"].time.time = original_time


def test_store_selection():
    """Backend selection flows through explicit AppSettings instances;
    invalid values are rejected at settings construction (B2-4)."""
    from pydantic import ValidationError

    from backend.core.config import AppSettings

    memory_cfg = AppSettings(_env_file=None, rate_limit_backend="memory")
    assert isinstance(create_rate_limit_store(memory_cfg), InMemoryRateLimitStore)
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, rate_limit_backend="invalid")


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


def test_redis_store_requires_url():
    from backend.core.config import AppSettings

    cfg = AppSettings(_env_file=None, rate_limit_backend="redis", redis_url=None)
    with pytest.raises(ValueError, match="Redis URL is required"):
        create_rate_limit_store(cfg)


def test_readme_documents_rate_limit_deployment() -> None:
    """Lock the user-facing memory-vs-Redis deployment guidance in README.

    Without this, the two backends' scoping (per-process vs. global) is
    documented only in ``.env.example`` and can silently drift.
    """
    from pathlib import Path

    readme = Path(__file__).resolve().parents[2] / "README.md"
    text = readme.read_text(encoding="utf-8")
    # Both backends are named.
    assert "SDM_RATE_LIMIT_BACKEND=memory" in text
    assert "SDM_RATE_LIMIT_BACKEND=redis" in text
    # The scoping contract is stated, not just implied.
    assert "per instance" in text.lower() or "per-process" in text.lower()
    assert "SDM_REDIS_URL" in text



# =============================================================================
# B2-4 — configuration flows through AppSettings (no raw env reads)
# =============================================================================

def test_b24_t1_default_backend_is_memory_without_redis(monkeypatch):
    """Default config: memory backend, no Redis URL, factory returns the
    in-memory store — local/single-process deployments never touch Redis."""
    monkeypatch.delenv("SDM_RATE_LIMIT_BACKEND", raising=False)
    monkeypatch.delenv("SDM_REDIS_URL", raising=False)
    from backend.core.config import AppSettings

    cfg = AppSettings(_env_file=None)
    assert cfg.rate_limit_backend == "memory"
    assert cfg.redis_url is None
    assert isinstance(create_rate_limit_store(cfg), InMemoryRateLimitStore)


def test_b24_t2_settings_selects_redis_with_fake_client(monkeypatch):
    """Explicit redis Settings select RedisRateLimitStore through the
    factory, using the existing fake-redis isolation (no live Redis)."""
    from backend.core.config import AppSettings

    class FakeClient:
        def ping(self):
            return True

        def register_script(self, script):
            def invoke(*, keys, args):
                return [1, 60]

            return invoke

    fake_redis = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *args, **kwargs: FakeClient())
    )
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    cfg = AppSettings(
        _env_file=None,
        rate_limit_backend="redis",
        redis_url="redis://localhost/0",
    )
    store = create_rate_limit_store(cfg)
    assert isinstance(store, RedisRateLimitStore)
    assert store.check("client", 3, 60)[0] is True


def test_b24_t3_redis_without_url_fails_fast_not_downgrade():
    """Redis backend without a URL raises immediately — never silently
    downgrades to the memory store."""
    from backend.core.config import AppSettings

    cfg = AppSettings(_env_file=None, rate_limit_backend="redis", redis_url=None)
    with pytest.raises(ValueError, match="Redis URL is required"):
        create_rate_limit_store(cfg)


def test_b24_t3_redis_with_empty_url_fails_fast():
    from backend.core.config import AppSettings

    cfg = AppSettings(_env_file=None, rate_limit_backend="redis", redis_url="")
    with pytest.raises(ValueError, match="Redis URL is required"):
        create_rate_limit_store(cfg)


def test_b24_t4_invalid_backend_rejected_at_settings_construction():
    """Invalid backend values fail at configuration validation with a
    clear error — they are never silently accepted."""
    from pydantic import ValidationError

    from backend.core.config import AppSettings

    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, rate_limit_backend="invalid")


def test_b24_t4_no_case_or_whitespace_normalization():
    """Documented decision: backend values are strict lowercase with no
    case/whitespace normalization — 'REDIS' or ' redis ' are rejected,
    not coerced."""
    from pydantic import ValidationError

    from backend.core.config import AppSettings

    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, rate_limit_backend="REDIS")
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, rate_limit_backend=" redis ")


def test_b24_t4_factory_boundary_guard_for_untyped_input():
    """The factory keeps a boundary guard for untyped callers: an
    unexpected backend value raises the familiar ValueError, never a
    silent downgrade."""
    bogus = types.SimpleNamespace(rate_limit_backend="bogus")
    with pytest.raises(ValueError, match="expected 'memory' or 'redis'"):
        create_rate_limit_store(bogus)


def test_b24_t5_secret_url_masked_in_repr_and_serialization():
    """The Redis URL is SecretStr: repr, JSON serialization and model
    dumps never expose the password."""
    from backend.core.config import AppSettings

    cfg = AppSettings(
        _env_file=None,
        rate_limit_backend="redis",
        redis_url="redis://:hunter2secret@localhost/0",
    )
    # The factory-facing accessor still yields the real value.
    assert cfg.redis_url.get_secret_value() == "redis://:hunter2secret@localhost/0"
    assert "hunter2secret" not in repr(cfg)
    assert "hunter2secret" not in cfg.model_dump_json()
    assert "hunter2secret" not in str(cfg.model_dump())


def test_b24_t5_factory_error_does_not_leak_url():
    from backend.core.config import AppSettings

    cfg = AppSettings(_env_file=None, rate_limit_backend="redis", redis_url=None)
    with pytest.raises(ValueError) as excinfo:
        create_rate_limit_store(cfg)
    assert "redis://" not in str(excinfo.value)


def test_b24_t6_env_vars_map_through_settings(monkeypatch):
    """SDM_RATE_LIMIT_BACKEND / SDM_REDIS_URL load through the unified
    SDM_ prefix mechanism, isolated from any .env file."""
    from backend.core.config import AppSettings

    monkeypatch.setenv("SDM_RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("SDM_REDIS_URL", "redis://:envpass@localhost/0")
    cfg = AppSettings(_env_file=None)
    assert cfg.rate_limit_backend == "redis"
    assert cfg.redis_url.get_secret_value() == "redis://:envpass@localhost/0"
    assert "envpass" not in repr(cfg)


def test_b24_t6_env_absent_defaults_to_memory(monkeypatch):
    from backend.core.config import AppSettings

    monkeypatch.delenv("SDM_RATE_LIMIT_BACKEND", raising=False)
    monkeypatch.delenv("SDM_REDIS_URL", raising=False)
    cfg = AppSettings(_env_file=None)
    assert cfg.rate_limit_backend == "memory"
    assert cfg.redis_url is None
