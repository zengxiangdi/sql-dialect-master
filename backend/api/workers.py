"""Bound synchronous work even when an HTTP caller times out."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore


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

    async def run(self, function, *args, timeout: float):
        if not self._slots.acquire(blocking=False):
            raise WorkerCapacityError("Request processing capacity is exhausted")
        try:
            future = self._executor.submit(function, *args)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _future: self._slots.release())
        wrapped = asyncio.wrap_future(future)
        # A timed-out caller no longer awaits this result. Retrieve exceptions
        # to avoid an unhandled-future warning when background work later fails.
        wrapped.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())
        return await asyncio.wait_for(asyncio.shield(wrapped), timeout=timeout)

    def shutdown(self) -> None:
        """Cancel queued work; already-running calls retain their slots."""
        self._executor.shutdown(wait=False, cancel_futures=True)
