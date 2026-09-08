"""Regression tests for runtime transpilation error taxonomy."""

from backend.core.exceptions import ErrorCode
from backend.core.transpiler import SQLTranspiler


def test_unsupported_dialect_has_stable_error_code() -> None:
    result = SQLTranspiler().transpile("SELECT 1", "not_a_dialect", "postgres")
    assert result.success is False
    assert result.error_code == ErrorCode.UNSUPPORTED_DIALECT.value
    assert result.to_dict()["error_code"] == ErrorCode.UNSUPPORTED_DIALECT.value


def test_empty_sql_has_validation_error_code() -> None:
    result = SQLTranspiler().transpile("   ", "mysql", "postgres")
    assert result.success is False
    assert result.error_code == ErrorCode.VALIDATION_FAILED.value


def test_security_block_has_security_error_code(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.core.transpiler.settings.security_block_dangerous",
        True,
    )
    transpiler = SQLTranspiler()
    result = transpiler.transpile(
        "SELECT 1; SELECT 2",
        "mysql",
        "postgres",
    )
    assert result.success is False
    assert result.error_code == ErrorCode.SECURITY_VIOLATION.value


def test_output_validation_failure_has_validation_error_code(monkeypatch) -> None:
    transpiler = SQLTranspiler()

    def invalid_process(sql, source, target):
        return "SELECT FROM", ["synthetic invalid transformation"]

    monkeypatch.setattr(transpiler.post_processor, "process", invalid_process)
    result = transpiler.transpile("SELECT id FROM users", "mysql", "postgres")

    assert result.success is False
    assert result.error_code == ErrorCode.VALIDATION_FAILED.value
    assert result.target_sql is None


def test_unexpected_transpile_exception_has_transpile_error_code(monkeypatch) -> None:
    transpiler = SQLTranspiler()

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr("backend.core.transpiler.sqlglot.transpile", explode)
    result = transpiler.transpile("SELECT 1", "mysql", "postgres")

    assert result.success is False
    assert result.error_code == ErrorCode.TRANSPILE_FAILED.value
