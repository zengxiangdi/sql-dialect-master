from backend.core.cache import CachedFunction, TTLCache


def test_get_or_set_caches_none_value_once() -> None:
    cache = TTLCache(max_size=2, ttl=60)
    calls = 0

    def factory() -> None:
        nonlocal calls
        calls += 1
        return None

    assert cache.get_or_set("none", factory) is None
    assert cache.get_or_set("none", factory) is None
    assert calls == 1
    assert cache.get_stats()["hits"] == 1


def test_cached_function_caches_none_value_once() -> None:
    calls = 0
    cache = TTLCache(max_size=2, ttl=60)

    @CachedFunction(cache=cache)
    def build_value() -> None:
        nonlocal calls
        calls += 1
        return None

    assert build_value() is None
    assert build_value() is None
    assert calls == 1
    assert cache.get_stats()["hits"] == 1
