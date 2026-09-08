import pytest
from pydantic import ValidationError

from backend.core.config import AppSettings


def test_cache_max_size_must_be_positive():
    with pytest.raises(ValidationError):
        AppSettings(cache_max_size=0)

    with pytest.raises(ValidationError):
        AppSettings(cache_max_size=-1)


def test_cache_max_size_accepts_positive_value():
    settings = AppSettings(cache_max_size=1)
    assert settings.cache_max_size == 1
