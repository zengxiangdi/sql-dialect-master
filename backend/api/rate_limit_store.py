"""Shared rate-limit backends.

Redis is opt-in. The in-memory backend remains the default for local/single-process use.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Optional, Protocol

from backend.core.config import AppSettings, settings as _default_settings


class RateLimitStore(Protocol):
    """Minimal storage contract used by RateLimiter."""

    def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        """Return allowed, remaining, and reset seconds."""

    def stats(self) -> dict:
        """Return storage metadata."""


class InMemoryRateLimitStore:
    """Thread-safe fixed-window store for a single process."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, float]] = {}
        self._expirations: dict[str, float] = {}
        self._next_cleanup_at = 0.0
        self._lock = Lock()

    def _prune_expired(self, now: float) -> None:
        if now < self._next_cleanup_at:
            return
        expired_keys = [
            key for key, expires_at in self._expirations.items() if expires_at <= now
        ]
        for key in expired_keys:
            self._entries.pop(key, None)
            self._expirations.pop(key, None)
        self._next_cleanup_at = min(self._expirations.values(), default=float("inf"))

    def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        with self._lock:
            now = time.monotonic()
            self._prune_expired(now)
            count, window_start = self._entries.get(key, (0, now))
            if now - window_start >= window_seconds:
                count, window_start = 0, now
            count += 1
            expires_at = window_start + window_seconds
            self._entries[key] = (count, window_start)
            self._expirations[key] = expires_at
            self._next_cleanup_at = min(self._next_cleanup_at, expires_at)
            return count <= limit, max(0, limit - count), max(0, int(expires_at - now))

    def stats(self) -> dict:
        with self._lock:
            self._prune_expired(time.monotonic())
            return {"backend": "memory", "active_clients": len(self._entries)}


class RedisRateLimitStore:
    """Atomic fixed-window store backed by Redis for multi-worker deployments."""

    DEFAULT_TIMEOUT_SECONDS = 3.0

    _SCRIPT = """
    local count = redis.call('INCR', KEYS[1])
    if count == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    local ttl = redis.call('TTL', KEYS[1])
    return {count, ttl}
    """

    def __init__(
        self,
        url: str,
        namespace: str = "sdm:rate-limit:",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not url:
            raise ValueError("Redis URL is required when rate-limit backend is redis")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("Redis rate limiting requires the optional 'redis' package") from exc
        # Bound both connection establishment and command execution.  A
        # stalled Redis node must not block API startup or every request that
        # checks the distributed rate-limit store.
        self._client = redis.Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )
        self._client.ping()
        self._script = self._client.register_script(self._SCRIPT)
        self._namespace = namespace

    def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        values = self._script(keys=[f"{self._namespace}{key}"], args=[window_seconds])
        count = int(values[0])
        ttl = max(0, int(values[1]))
        return count <= limit, max(0, limit - count), ttl

    def stats(self) -> dict:
        return {"backend": "redis", "namespace": self._namespace}


def create_rate_limit_store(config: Optional[AppSettings] = None) -> RateLimitStore:
    """Create the configured store; never silently downgrade Redis to memory.

    Reads configuration from ``config``, or from the unified
    ``backend.core.config.settings`` singleton when ``config`` is None.
    The factory never reads raw environment variables — all deployment
    configuration flows through AppSettings (SDM_ prefix), so backend
    selection and the Redis URL share one validated configuration path.

    The Redis URL is a SecretStr in AppSettings; its actual value is
    read here only to construct the Redis client, and it is never
    embedded in error messages or logs.
    """
    settings_obj = config if config is not None else _default_settings
    backend = settings_obj.rate_limit_backend
    if backend == "memory":
        return InMemoryRateLimitStore()
    if backend == "redis":
        url = settings_obj.redis_url
        url_value = url.get_secret_value() if url is not None else ""
        return RedisRateLimitStore(url_value)
    # Boundary guard for untyped callers: only reachable when a caller
    # passes a non-AppSettings object with an unexpected backend value
    # (typed AppSettings validation rejects it earlier).
    raise ValueError("Unsupported rate_limit_backend; expected 'memory' or 'redis'")
