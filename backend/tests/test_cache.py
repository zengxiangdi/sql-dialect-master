#!/usr/bin/env python3
"""Unit tests for TTLCache module.

Tests caching functionality including:
- Basic get/set operations
- TTL expiration
- LRU eviction
- Thread safety
- Statistics
"""
import asyncio
import pytest
import time
import threading
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.cache import TTLCache, CacheEntry, CachedFunction
from backend.core.config import settings
from backend.core.transpiler import SQLTranspiler


class TestCacheEntry:
    def test_entry_not_expired_within_ttl(self):
        entry = CacheEntry(value="test", created_at=time.time(), ttl=10)
        assert not entry.is_expired()

    def test_entry_expired_after_ttl(self):
        entry = CacheEntry(value="test", created_at=time.time() - 11, ttl=10)
        assert entry.is_expired()

    def test_entry_never_expires_with_zero_ttl(self):
        entry = CacheEntry(value="test", created_at=time.time() - 1000, ttl=0)
        assert not entry.is_expired()

    def test_entry_tracks_hits(self):
        entry = CacheEntry(value="test", created_at=time.time(), ttl=60)
        assert entry.hits == 0
        entry.hits += 1
        assert entry.hits == 1


class TestTTLCache:
    def test_set_and_get(self):
        cache = TTLCache(max_size=10, ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_security_policy_change_is_part_of_cache_identity(self, monkeypatch):
        """Changing warning/block mode must not reuse a result cached under another policy."""
        transpiler = SQLTranspiler()
        sql = "SELECT * FROM users WHERE id = 1 OR 1=1"

        monkeypatch.setattr(settings, "security_block_dangerous", False)
        warned = transpiler.transpile(sql, "mysql", "postgres")
        assert warned.success
        assert any(w.startswith("🔒 Security:") for w in warned.warnings)

        monkeypatch.setattr(settings, "security_block_dangerous", True)
        blocked = transpiler.transpile(sql, "mysql", "postgres")
        assert not blocked.success
        assert "Security check failed" in blocked.error

    def test_get_nonexistent_key(self):
        cache = TTLCache()
        assert cache.get("nonexistent") is None

    def test_delete_key(self):
        cache = TTLCache()
        cache.set("key1", "value1")
        deleted = cache.delete("key1")
        assert deleted is True
        assert cache.get("key1") is None

    def test_delete_nonexistent_key(self):
        cache = TTLCache()
        deleted = cache.delete("nonexistent")
        assert deleted is False

    def test_lru_eviction(self):
        cache = TTLCache(max_size=2, ttl=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_lru_updates_on_access(self):
        cache = TTLCache(max_size=2, ttl=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.get("key1")
        cache.set("key3", "value3")
        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None
        assert cache.get("key3") == "value3"

    def test_updating_existing_key_does_not_evict_other_entries(self):
        cache = TTLCache(max_size=2, ttl=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key2", "updated")
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "updated"
        assert cache.get_stats()["evictions"] == 0

    def test_invalid_max_size_is_rejected(self):
        with pytest.raises(ValueError, match="max_size must be greater than 0"):
            TTLCache(max_size=0)
        with pytest.raises(ValueError, match="max_size must be greater than 0"):
            TTLCache(max_size=-1)

    def test_clear(self):
        cache = TTLCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert len(cache) == 0
        assert cache.get("key1") is None

    def test_cleanup_expired(self):
        cache = TTLCache(ttl=1)
        cache.set("key1", "value1")
        time.sleep(1.5)
        removed = cache.cleanup_expired()
        assert removed == 1
        assert cache.get("key1") is None

    def test_async_get_and_set_use_running_loop(self):
        cache = TTLCache(ttl=60)

        async def exercise() -> None:
            await cache.set_async("key1", "value1")
            assert await cache.get_async("key1") == "value1"

        asyncio.run(exercise())

    def test_contains(self):
        cache = TTLCache()
        cache.set("key1", "value1")
        assert "key1" in cache
        assert "nonexistent" not in cache

    def test_len(self):
        cache = TTLCache()
        assert len(cache) == 0
        cache.set("key1", "value1")
        assert len(cache) == 1
        cache.set("key2", "value2")
        assert len(cache) == 2

    def test_stats(self):
        cache = TTLCache(max_size=10, ttl=60)
        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("key2")
        stats = cache.get_stats()
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["max_size"] == 10
        assert stats["ttl"] == 60

    def test_custom_ttl_on_set(self):
        cache = TTLCache(ttl=60)
        cache.set("key1", "value1", ttl=1)
        assert cache.get("key1") == "value1"
        time.sleep(1.5)
        assert cache.get("key1") is None

    def test_thread_safety(self):
        cache = TTLCache(max_size=100, ttl=60)
        errors = []

        def writer():
            try:
                for i in range(100):
                    cache.set(f"key{i}", f"value{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    cache.get(f"key{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(5)]
        threads += [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0


class TestGetOrSet:
    """get_or_set contract: factory runs outside the lock, value is cached."""

    def test_get_or_set_caches_miss_value(self):
        cache = TTLCache(ttl=60)
        calls = []

        def factory():
            calls.append(1)
            return "computed"

        assert cache.get_or_set("k", factory) == "computed"
        assert calls == [1]
        # Second call is a hit — factory must not run again.
        assert cache.get_or_set("k", factory) == "computed"
        assert calls == [1]

    def test_get_or_set_hits_do_not_call_factory(self):
        cache = TTLCache(ttl=60)
        cache.set("preset", "preloaded")
        assert cache.get_or_set("preset", lambda: "should_not_run") == "preloaded"

    def test_factory_runs_without_holding_the_lock(self):
        """A concurrent reader must not be blocked for the factory's duration.

        If ``get_or_set`` still ran the factory under the lock, a reader on
        another thread calling ``get`` would wait for the whole factory to
        finish.  We measure the reader's wall-time against a factory that
        sleeps, and assert the reader acquired the lock promptly.
        """
        cache = TTLCache(ttl=60)
        factory_started = threading.Event()
        reader_elapsed_box: list = []

        def slow_factory():
            factory_started.set()
            time.sleep(0.25)
            return "done"

        def reader():
            while not factory_started.is_set():
                time.sleep(0.001)
            # Give the factory a beat to enter and start sleeping so the
            # reader's get() lands squarely inside the factory window.
            time.sleep(0.05)
            start = time.perf_counter()
            cache.get("unrelated")
            reader_elapsed_box.append(time.perf_counter() - start)

        main_start = time.perf_counter()
        t = threading.Thread(target=reader)
        t.start()
        result = cache.get_or_set("k", slow_factory)
        main_wall = time.perf_counter() - main_start
        t.join()
        assert result == "done"
        # The main thread still waited for the factory to compute the value
        # (it is the caller), but the reader was not serialized behind it.
        assert main_wall >= 0.25, "main thread unexpectedly fast"
        assert reader_elapsed_box and reader_elapsed_box[0] < 0.2, (
            "reader was blocked on the cache lock during factory compute"
        )


class TestCachedFunction:
    def test_decorator_caches_result(self):
        call_count = 0
        cache = TTLCache(ttl=60)

        @CachedFunction(cache=cache)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = expensive_function(5)
        result2 = expensive_function(5)
        assert result1 == 10
        assert result2 == 10
        assert call_count == 1

    def test_decorator_different_args(self):
        call_count = 0
        cache = TTLCache(ttl=60)

        @CachedFunction(cache=cache)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = expensive_function(5)
        result2 = expensive_function(10)
        assert result1 == 10
        assert result2 == 20
        assert call_count == 2


class TestMakeKey:
    def test_make_key_consistent(self):
        cache = TTLCache()
        key1 = cache._make_key("a", "b", foo="bar")
        key2 = cache._make_key("a", "b", foo="bar")
        assert key1 == key2

    def test_make_key_different_args(self):
        cache = TTLCache()
        key1 = cache._make_key("a", "b")
        key2 = cache._make_key("a", "c")
        assert key1 != key2

    def test_make_key_kwargs_order_independent(self):
        cache = TTLCache()
        key1 = cache._make_key(a=1, b=2)
        key2 = cache._make_key(b=2, a=1)
        assert key1 == key2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
