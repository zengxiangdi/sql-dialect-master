import pytest

from backend.api.middleware import RateLimiter


def test_rate_limiter_rejects_non_positive_configuration() -> None:
    with pytest.raises(ValueError, match="requests_per_window must be positive"):
        RateLimiter(requests_per_window=0)
    with pytest.raises(ValueError, match="window_seconds must be positive"):
        RateLimiter(window_seconds=0)


def test_rate_limiter_prunes_expired_clients(monkeypatch) -> None:
    current_time = 1000.0
    monkeypatch.setattr("backend.api.middleware.time.time", lambda: current_time)

    limiter = RateLimiter(requests_per_window=10, window_seconds=60)
    limiter.is_allowed("stale-client")

    current_time = 1061.0
    limiter.is_allowed("fresh-client")

    assert "stale-client" not in limiter._limits
    assert limiter.get_stats()["active_clients"] == 1
