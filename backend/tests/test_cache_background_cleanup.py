import pytest

from backend.core.cache import TTLCache


def test_background_cleanup_rejects_non_positive_interval() -> None:
    cache = TTLCache()

    with pytest.raises(ValueError, match="interval must be positive"):
        cache.start_background_cleanup(interval=0)

    with pytest.raises(ValueError, match="interval must be positive"):
        cache.start_background_cleanup(interval=-1)
