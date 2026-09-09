from backend.core.cache import TTLCache


def test_get_or_set_caches_none_value_once() -> None:
    cache = TTLCache(max_size=2, ttl=60)
    calls = 0

    def factory() -> None:
        nonlocal calls
        calls += 1
        return None

    assert cache.get_or_set("none", factory) is None
    assert cache.get_or_set("none", factory) is None
    assert calls == 2
