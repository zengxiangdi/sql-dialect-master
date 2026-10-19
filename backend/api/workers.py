"""Bound synchronous work even when an HTTP caller times out."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock


class WorkerCapacityError(RuntimeError):
    """All execution and queue slots are occupied."""


class BoundedWorkerPool:
    """Keep a slot until its underlying future finishes, including timeouts.

    Cancelling an HTTP wait cannot interrupt Python threads. Holding capacity
    until completion prevents a stream of timed-out requests from creating an
    unbounded executor queue. Slots cover executing and queued work together.
    """

    def __init__(self, workers: int, queue_size: int = 0):
        if workers <= 0 or queue_size < 0:
            raise ValueError("workers must be positive and queue_size non-negative")
        self._slots = BoundedSemaphore(workers + queue_size)
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sdm-api")
        self._shutdown_lock = Lock()
        self._stats_lock = Lock()
        self._capacity = workers + queue_size
        self._in_use = 0
        self._rejections = 0
        self._timeouts = 0
        self._shutdown = False

    async def run(self, function, *args, timeout: float):
        if not self._slots.acquire(blocking=False):
            with self._stats_lock:
                self._rejections += 1
            raise WorkerCapacityError("Request processing capacity is exhausted")
        with self._stats_lock:
            self._in_use += 1
        try:
            future = self._executor.submit(function, *args)
        except BaseException:
            self._slots.release()
            with self._stats_lock:
                self._in_use -= 1
            raise

        def release_slot(_future):
            self._slots.release()
            with self._stats_lock:
                self._in_use -= 1

        future.add_done_callback(release_slot)
        wrapped = asyncio.wrap_future(future)
        # A timed-out caller no longer awaits this result. Retrieve exceptions
        # to avoid an unhandled-future warning when background work later fails.
        wrapped.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), timeout=timeout)
        except asyncio.TimeoutError:
            with self._stats_lock:
                self._timeouts += 1
            raise

    def stats(self) -> dict[str, int]:
        """Return a thread-safe snapshot of pool capacity counters."""
        with self._stats_lock:
            return {
                "capacity": self._capacity,
                "in_use": self._in_use,
                "rejections": self._rejections,
                "timeouts": self._timeouts,
            }

    def shutdown(self) -> None:
        """Cancel queued work; already-running calls retain their slots."""
        with self._shutdown_lock:
            if self._shutdown:
                return
            self._shutdown = True
        self._executor.shutdown(wait=False, cancel_futures=True)
