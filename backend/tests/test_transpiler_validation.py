"""Regression tests for transpiler output validation."""

from backend.core.transpiler import SQLTranspiler


def test_invalid_post_processed_sql_is_reported_as_failure(monkeypatch) -> None:
    """A post-processor that emits invalid SQL must not yield success=True."""
    transpiler = SQLTranspiler()

    def invalid_process(sql: str, source: str, target: str):
        return "SELECT FROM", ["synthetic invalid transformation"]

    monkeypatch.setattr(transpiler.post_processor, "process", invalid_process)

    result = transpiler.transpile(
        "SELECT id FROM users",
        "mysql",
        "postgres",
    )

    assert result.success is False
    assert result.target_sql is None
    assert result.error is not None
    assert "syntax issues" in result.error.lower()
    assert result.transformations == ["synthetic invalid transformation"]
