"""Regression tests for packaged runtime data loading failures."""

import json

import pytest

from backend.core.exceptions import ConfigurationError, ErrorCode
from backend.core.functions_lookup import FunctionEncyclopedia


def test_missing_function_data_fails_with_configuration_error(tmp_path) -> None:
    missing = tmp_path / "missing-functions.json"

    with pytest.raises(ConfigurationError) as exc_info:
        FunctionEncyclopedia(data_path=missing)

    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID
    assert "missing-functions.json" in exc_info.value.message


def test_malformed_function_data_fails_with_configuration_error(tmp_path) -> None:
    path = tmp_path / "functions.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        FunctionEncyclopedia(data_path=path)

    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID


def test_invalid_function_data_schema_fails_with_configuration_error(tmp_path) -> None:
    path = tmp_path / "functions.json"
    path.write_text(json.dumps({"functions": {"COUNT": "invalid"}}), encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        FunctionEncyclopedia(data_path=path)

    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID
