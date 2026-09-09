import asyncio
import time

from backend.api import readiness


def test_readiness_cache_refreshes_after_ttl(monkeypatch):
    async def exercise():
        calls = 0

        def fake_probe():
            nonlocal calls
            calls += 1
            return {"transpiler": {"status": "ok"}}

        monkeypatch.setattr(readiness, "_run_checks", fake_probe)
        original_ttl = readiness._READINESS_CACHE_TTL_SECONDS
        readiness._READINESS_CACHE_TTL_SECONDS = 30.0
        readiness._cached_checks = {"transpiler": {"status": "stale"}}
        readiness._cached_at = time.monotonic() - 31.0
        try:
            first = await readiness._get_checks()
            second = await readiness._get_checks()
            assert first == {"transpiler": {"status": "ok"}}
            assert second == first
            assert calls == 1
        finally:
            readiness._READINESS_CACHE_TTL_SECONDS = original_ttl
            readiness._cached_checks = None
            readiness._cached_at = 0.0
            readiness._READINESS_CACHE["checks"] = None
            readiness._READINESS_CACHE["cached_at"] = 0.0

    asyncio.run(exercise())
