import pytest

from backend.core.cache import TTLCache


def test_background_cleanup_rejects_non_positive_interval() -> None:
    cache = TTLCache()

    with pytest.raises(ValueError, match="interval must be positive"):
        cache.start_background_cleanup(interval=0)

    with pytest.raises(ValueError, match="interval must be positive"):
        cache.start_background_cleanup(interval=-1)


def test_background_cleanup_is_not_restarted_while_running() -> None:
    """A second call while the first thread is alive must fail fast.

    Without this guard, every call would spawn another daemon thread that
    loops forever, leaking a thread per call.
    """
    cache = TTLCache()
    first = cache.start_background_cleanup(interval=60)
    assert first.is_alive()
    with pytest.raises(RuntimeError, match="already running"):
        cache.start_background_cleanup(interval=60)
