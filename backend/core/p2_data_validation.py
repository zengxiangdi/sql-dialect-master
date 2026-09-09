"""Reusable validators for packaged runtime JSON data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import FUNCTION_CATEGORIES, SUPPORTED_DIALECTS
from .exceptions import ConfigurationError


def _error(path: Path, message: str) -> ConfigurationError:
    return ConfigurationError(
        f"Invalid runtime data in {path}: {message}",
        details={"data_path": str(path)},
    )


def _validate_function_entry(data_path: Path, index: int, entry: Any) -> None:
    prefix = f"functions[{index}]"
    if not isinstance(entry, dict):
        raise _error(data_path, f"'{prefix}' must be an object")
    name = entry.get("name")
    category = entry.get("category")
    dialects = entry.get("dialects")
    if not isinstance(name, str) or not name.strip():
        raise _error(data_path, f"'{prefix}.name' must be a non-empty string")
    if not isinstance(category, str) or category.lower() not in FUNCTION_CATEGORIES:
        raise _error(data_path, f"'{prefix}.category' must be a supported category")
    if not isinstance(entry.get("description", ""), str) or not isinstance(entry.get("notes", ""), str):
        raise _error(data_path, f"'{prefix}.description' and '{prefix}.notes' must be strings")
    if not isinstance(dialects, dict):
        raise _error(data_path, f"'{prefix}.dialects' must be an object")
    unknown = sorted(set(dialects) - set(SUPPORTED_DIALECTS))
    if unknown:
        raise _error(data_path, f"'{prefix}.dialects' contains unsupported dialects: {unknown}")
    if any(not isinstance(value, str) for value in dialects.values()):
        raise _error(data_path, f"'{prefix}.dialects' values must be strings")

    parameters = entry.get("parameters", [])
    if not isinstance(parameters, list):
        raise _error(data_path, f"'{prefix}.parameters' must be a list")
    for pidx, parameter in enumerate(parameters):
        if not isinstance(parameter, dict):
            raise _error(data_path, f"'{prefix}.parameters[{pidx}]' must be an object")
        for key in ("name", "type", "description"):
            if not isinstance(parameter.get(key), str):
                raise _error(data_path, f"'{prefix}.parameters[{pidx}].{key}' must be a string")
        if not isinstance(parameter.get("required"), bool):
            raise _error(data_path, f"'{prefix}.parameters[{pidx}].required' must be boolean")

    examples = entry.get("examples", {})
    if not isinstance(examples, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in examples.items()
    ):
        raise _error(data_path, f"'{prefix}.examples' must map strings to strings")


def _validate_type_mapping_entry(data_path: Path, name: Any, entry: Any) -> None:
    if not isinstance(name, str) or not name.strip():
        raise _error(data_path, "mapping keys must be non-empty strings")
    if not isinstance(entry, dict):
        raise _error(data_path, f"mappings[{name!r}] must be an object")
    unknown = sorted(set(entry) - (set(SUPPORTED_DIALECTS) | {"notes"}))
    if unknown:
        raise _error(data_path, f"mappings[{name!r}] contains unsupported keys: {unknown}")
    for dialect, value in entry.items():
        if dialect == "notes":
            if not isinstance(value, str):
                raise _error(data_path, f"mappings[{name!r}].notes must be a string")
        elif not isinstance(value, str) or not value.strip():
            raise _error(data_path, f"mappings[{name!r}].{dialect} must be a non-empty string")
