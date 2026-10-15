"""Shared test isolation for process-level API services."""

import pytest


@pytest.fixture(autouse=True)
def reset_global_api_rate_limit_store():
    """Keep TestClient cases independent from the process-wide limiter.

    Production requests intentionally share one limiter. TestClient instances
    use the same imported FastAPI app, so without isolation an unrelated test
    can exhaust the default window and turn a later validation assertion into
    a flaky 429.
    """
    try:
        from backend.api.main import rate_limiter

        store = getattr(rate_limiter, "_store", None)
        entries = getattr(store, "_entries", None)
        expirations = getattr(store, "_expirations", None)
        if isinstance(entries, dict):
            entries.clear()
        if isinstance(expirations, dict):
            expirations.clear()
    except ImportError:
        pass
    yield
