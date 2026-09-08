import asyncio

import pytest

from backend.core.config import settings
from backend.core.exceptions import ErrorCode, ValidationError
from backend.core.transpiler import SQLTranspiler


def test_batch_transpile_rejects_oversized_input(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_batch_size", 2)
    transpiler = SQLTranspiler()

    with pytest.raises(ValidationError) as exc_info:
        transpiler.batch_transpile(
            ["SELECT 1", "SELECT 2", "SELECT 3"],
            "mysql",
            "postgres",
        )

    error = exc_info.value
    assert error.error_code == ErrorCode.VALIDATION_FAILED
    assert error.details["field"] == "statements"
    assert error.details["value"] == "3"


def test_batch_transpile_async_rejects_oversized_input(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_batch_size", 2)
    transpiler = SQLTranspiler()

    with pytest.raises(ValidationError) as exc_info:
        asyncio.run(
            transpiler.batch_transpile_async(
                ["SELECT 1", "SELECT 2", "SELECT 3"],
                "mysql",
                "postgres",
            )
        )

    error = exc_info.value
    assert error.error_code == ErrorCode.VALIDATION_FAILED
    assert error.details["field"] == "statements"
    assert error.details["value"] == "3"
