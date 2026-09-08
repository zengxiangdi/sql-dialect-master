"""Regression tests for transpiler output validation and cache versioning."""

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


def test_cache_key_changes_when_rule_version_changes() -> None:
    """Changing a transformation rule must invalidate prior cache entries."""
    transpiler = SQLTranspiler()

    before = transpiler._cache_key("SELECT 1", "mysql", "postgres", True)
    transpiler.post_processor.engine.rules[0].enabled = not transpiler.post_processor.engine.rules[0].enabled
    after = transpiler._cache_key("SELECT 1", "mysql", "postgres", True)

    assert before != after


def test_cache_key_includes_validation_mode() -> None:
    """Validated and non-validated conversions must not share cache entries."""
    transpiler = SQLTranspiler()

    validated = transpiler._cache_key("SELECT 1", "mysql", "postgres", True, True)
    unvalidated = transpiler._cache_key("SELECT 1", "mysql", "postgres", True, False)

    assert validated != unvalidated
