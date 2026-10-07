"""Regression tests for public TypedDict result contracts."""

from typing import Optional, get_type_hints

from backend.core.config import TranspileResultDict


def test_transpile_result_dict_declares_error_code() -> None:
    annotations = get_type_hints(TranspileResultDict)
    assert "error_code" in annotations
    assert annotations["error_code"] == Optional[str]


def test_transpile_result_dict_accepts_machine_readable_error_code() -> None:
    result: TranspileResultDict = {
        "success": False,
        "source_sql": "SELECT 1",
        "target_sql": None,
        "source_dialect": "mysql",
        "target_dialect": "postgres",
        "error": "validation failed",
        "error_code": "VALIDATION_FAILED",
    }

    assert result["error_code"] == "VALIDATION_FAILED"


def test_transpile_result_dict_declares_target_validation_state() -> None:
    annotations = get_type_hints(TranspileResultDict)
    assert "target_validation_state" in annotations
    assert annotations["target_validation_state"] == str


def test_transpile_result_dict_accepts_target_validation_state() -> None:
    result: TranspileResultDict = {
        "success": True,
        "source_sql": "SELECT 1",
        "target_sql": "SELECT 1",
        "source_dialect": "postgres",
        "target_dialect": "mysql",
        "target_validation_state": "generic_only",
    }

    assert result["target_validation_state"] == "generic_only"
