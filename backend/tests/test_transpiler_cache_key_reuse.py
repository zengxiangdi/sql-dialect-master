from backend.core.config import settings
from backend.core.transpiler import SQLTranspiler


def test_cache_miss_reuses_computed_key_for_cache_set(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", False)

    transpiler = SQLTranspiler()
    transpiler._cache_enabled = True
    transpiler._cache.clear()

    calls = []
    original_cache_key = transpiler._cache_key

    def spy_cache_key(sql, source, target, pretty, validate):
        calls.append(1)
        return original_cache_key(sql, source, target, pretty, validate)

    monkeypatch.setattr(transpiler, "_cache_key", spy_cache_key)

    result = transpiler.transpile("SELECT 1", "mysql", "postgres")

    assert result.success is True
    assert len(calls) == 1


def test_cache_hit_still_computes_key_once(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", False)

    transpiler = SQLTranspiler()
    transpiler._cache_enabled = True
    transpiler._cache.clear()

    first = transpiler.transpile("SELECT 1", "mysql", "postgres")
    assert first.success is True

    calls = []
    original_cache_key = transpiler._cache_key

    def spy_cache_key(sql, source, target, pretty, validate):
        calls.append(1)
        return original_cache_key(sql, source, target, pretty, validate)

    monkeypatch.setattr(transpiler, "_cache_key", spy_cache_key)

    cached = transpiler.transpile("SELECT 1", "mysql", "postgres")

    assert cached.success is True
    assert cached.target_sql == first.target_sql
    assert len(calls) == 1
