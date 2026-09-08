"""Regression tests for packaged runtime data loading failures."""

import json

import pytest

from backend.core.exceptions import ConfigurationError, ErrorCode
from backend.core.functions_lookup import FunctionEncyclopedia
from backend.core.type_mapping import TypeMapper


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        "invalid",
        123,
    ],
)
def test_invalid_top_level_function_data_fails_with_configuration_error(
    tmp_path, payload
) -> None:
    path = tmp_path / "functions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        FunctionEncyclopedia(data_path=path)

    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID
    assert "top-level JSON value must be an object" in exc_info.value.message


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


def test_missing_type_mapping_data_fails_with_configuration_error(tmp_path) -> None:
    missing = tmp_path / "missing-type-mapping.json"

    with pytest.raises(ConfigurationError) as exc_info:
        TypeMapper(data_path=missing)

    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID
    assert "missing-type-mapping.json" in exc_info.value.message


def test_malformed_type_mapping_data_fails_with_configuration_error(tmp_path) -> None:
    path = tmp_path / "type_mapping.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        TypeMapper(data_path=path)

    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        "invalid",
        123,
    ],
)
def test_invalid_top_level_type_mapping_data_fails_with_configuration_error(
    tmp_path, payload
) -> None:
    path = tmp_path / "type_mapping.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        TypeMapper(data_path=path)

    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID
    assert "top-level JSON value must be an object" in exc_info.value.message


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"mappings": [], "precision_warnings": {}}, "'mappings' must be an object"),
        ({"mappings": {}, "precision_warnings": []}, "'precision_warnings' must be an object"),
    ],
)
def test_invalid_type_mapping_schema_fails_with_configuration_error(
    tmp_path, payload, message
) -> None:
    path = tmp_path / "type_mapping.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        TypeMapper(data_path=path)

    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID
    assert message in exc_info.value.message


def test_valid_type_mapping_data_still_loads(tmp_path) -> None:
    path = tmp_path / "type_mapping.json"
    path.write_text(
        json.dumps(
            {
                "mappings": {"INTEGER": {"postgres": "INTEGER", "mysql": "INT"}},
                "precision_warnings": {"DECIMAL": "Check precision"},
            }
        ),
        encoding="utf-8",
    )

    mapper = TypeMapper(data_path=path)

    assert mapper.get_all_types() == ["INTEGER"]
    assert mapper.get_precision_warnings() == {"DECIMAL": "Check precision"}
