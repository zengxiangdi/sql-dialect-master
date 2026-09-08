"""Regression tests for public TypedDict result contracts."""

from backend.core.config import TranspileResultDict


def test_transpile_result_dict_declares_error_code() -> None:
    annotations = TranspileResultDict.__annotations__
    assert "error_code" in annotations
    assert annotations["error_code"] == "Optional[str]"


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
