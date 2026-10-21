"""Behavioral boundary tests for shared API infrastructure."""

import asyncio
import ipaddress
import sys
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import Request
from sqlglot.errors import ParseError

from backend.api.client_identity import resolve_client_ip
from backend.api.rate_limit_store import InMemoryRateLimitStore, RedisRateLimitStore
from backend.api.workers import BoundedWorkerPool
from backend.core.config import settings
from backend.core.sql_statements import parse_single_sql


def test_forwarded_address_with_non_numeric_port_is_not_a_client_identity():
    request = Request({
        "type": "http",
        "client": ("192.0.2.10", 12345),
        "headers": [(b"x-forwarded-for", b"203.0.113.8:service")],
    })

    assert resolve_client_ip(request, (ipaddress.ip_network("192.0.2.0/24"),)) == "192.0.2.10"


@pytest.mark.parametrize("workers,queue_size", [(0, 0), (-1, 0), (1, -1)])
def test_worker_pool_rejects_invalid_capacity(workers, queue_size):
    with pytest.raises(ValueError, match="workers must be positive and queue_size non-negative"):
        BoundedWorkerPool(workers=workers, queue_size=queue_size)


def test_worker_shutdown_is_idempotent_and_cancels_only_queued_work():
    async def exercise():
        pool = BoundedWorkerPool(workers=1, queue_size=1)
        release = Event()
        started = asyncio.Event()
        loop = asyncio.get_running_loop()
        queued_calls = []

        def running_work():
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5), "test must release the running worker"
            return "finished"

        running = asyncio.create_task(pool.run(running_work, timeout=10))
        queued = None
        try:
            await asyncio.wait_for(started.wait(), 2)
            queued = asyncio.create_task(pool.run(lambda: queued_calls.append(True), timeout=10))
            # Let the second coroutine submit to the occupied executor.
            await asyncio.sleep(0)
            assert pool.stats()["in_use"] == 2

            pool.shutdown()
            pool.shutdown()

            with pytest.raises(asyncio.CancelledError):
                await queued
            assert queued_calls == []
            assert pool.stats()["in_use"] == 1
            release.set()
            assert await running == "finished"
            assert pool.stats()["in_use"] == 0
        finally:
            release.set()
            pool.shutdown()
            await asyncio.gather(running, *([queued] if queued is not None else []), return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("sql", [None, 1])
def test_single_statement_parser_rejects_non_string_input(sql):
    with pytest.raises(ParseError, match="SQL statement must be a string"):
        parse_single_sql(sql, "postgres")


@pytest.mark.parametrize("sql", ["", " \n\t"])
def test_single_statement_parser_rejects_empty_input(sql):
    with pytest.raises(ParseError, match="Empty SQL statement"):
        parse_single_sql(sql, "postgres")


def test_single_statement_parser_enforces_inclusive_length_limit(monkeypatch):
    monkeypatch.setattr(settings, "parser_max_sql_length", len("SELECT 1"))

    assert parse_single_sql("SELECT 1", "postgres").sql() == "SELECT 1"
    with pytest.raises(ParseError, match="SQL exceeds maximum length of 8 characters"):
        parse_single_sql("SELECT 10", "postgres")


def test_memory_store_resets_when_a_call_shortens_the_window(monkeypatch):
    now = 100.0
    monkeypatch.setattr("backend.api.rate_limit_store.time.monotonic", lambda: now)
    store = InMemoryRateLimitStore()
    assert store.check("client", 1, 60) == (True, 0, 60)

    now = 111.0
    assert store.check("client", 1, 10) == (True, 0, 10)
    assert store.check("client", 1, 10) == (False, 0, 10)
    now = 121.0
    assert store.stats() == {"backend": "memory", "active_clients": 0}


@pytest.mark.parametrize("timeout", [0, -1])
def test_redis_store_rejects_non_positive_timeouts(timeout):
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        RedisRateLimitStore("redis://localhost/0", timeout_seconds=timeout)


def test_redis_store_without_optional_package_fails_closed(monkeypatch):
    monkeypatch.setitem(sys.modules, "redis", None)

    with pytest.raises(RuntimeError, match="Redis rate limiting requires the optional 'redis' package"):
        RedisRateLimitStore("redis://localhost/0")


def test_redis_store_reports_namespace_and_clamps_expired_ttl(monkeypatch):
    class FakeClient:
        def ping(self):
            return True

        def register_script(self, _script):
            def invoke(*, keys, args):
                assert keys == ["test:client"]
                assert args == [60]
                return [3, -1]

            return invoke

    redis = SimpleNamespace(Redis=SimpleNamespace(from_url=lambda *_args, **_kwargs: FakeClient()))
    monkeypatch.setitem(sys.modules, "redis", redis)
    store = RedisRateLimitStore("redis://localhost/0", namespace="test:")

    assert store.stats() == {"backend": "redis", "namespace": "test:"}
    assert store.check("client", 2, 60) == (False, 0, 0)
