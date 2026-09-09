import json

import pytest

from backend.core.exceptions import ConfigurationError, ErrorCode
from backend.core.functions_lookup import FunctionEncyclopedia
from backend.core.type_mapping import TypeMapper


def valid_function():
    return {
        "name": "COUNT",
        "category": "aggregate",
        "description": "Count rows",
        "parameters": [{"name": "expr", "type": "expression", "required": True, "description": "Value"}],
        "dialects": {"postgres": "COUNT(expr)"},
        "examples": {"postgres": "SELECT COUNT(*)"},
        "notes": "",
    }


@pytest.mark.parametrize("entry, needle", [
    ({}, "name"),
    ({"name": "COUNT", "category": "bad", "dialects": {}}, "category"),
    ({"name": "COUNT", "category": "aggregate", "dialects": {"nope": "COUNT(x)"}}, "unsupported dialects"),
    ({**valid_function(), "parameters": [{"name": "x", "type": "x", "required": "yes", "description": "x"}]}, "required.*must be boolean"),
])
def test_invalid_function_entry_schema(tmp_path, entry, needle):
    path = tmp_path / "functions.json"
    path.write_text(json.dumps({"functions": [entry]}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=needle) as exc_info:
        FunctionEncyclopedia(data_path=path)
    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID


def test_valid_function_entry_loads(tmp_path):
    path = tmp_path / "functions.json"
    path.write_text(json.dumps({"functions": [valid_function()]}), encoding="utf-8")
    assert FunctionEncyclopedia(data_path=path).get_function("COUNT")["name"] == "COUNT"


@pytest.mark.parametrize("payload, needle", [
    ({"mappings": {"INTEGER": "INT"}, "precision_warnings": {}}, "must be an object"),
    ({"mappings": {"INTEGER": {"nope": "INT"}}, "precision_warnings": {}}, "unsupported keys"),
    ({"mappings": {"INTEGER": {"postgres": 123}}, "precision_warnings": {}}, "must be a non-empty string"),
    ({"mappings": {"INTEGER": {"postgres": "INT"}}, "precision_warnings": {"INTEGER": 123}}, "precision_warnings must map"),
])
def test_invalid_type_mapping_entry_schema(tmp_path, payload, needle):
    path = tmp_path / "type_mapping.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=needle) as exc_info:
        TypeMapper(data_path=path)
    assert exc_info.value.error_code == ErrorCode.CONFIGURATION_INVALID
