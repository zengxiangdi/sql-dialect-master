from backend.core.config import settings
from backend.core.transpiler import SQLTranspiler


def test_cache_hit_does_not_repeat_statement_validation(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", False)
    transpiler = SQLTranspiler()
    transpiler._cache_enabled = True

    calls = 0
    original_has_multiple = transpiler._has_multiple_statements

    def counted_has_multiple(sql):
        nonlocal calls
        calls += 1
        return original_has_multiple(sql)

    monkeypatch.setattr(transpiler, "_has_multiple_statements", counted_has_multiple)

    first = transpiler.transpile("SELECT 1", "mysql", "postgres", validate=False)
    second = transpiler.transpile("SELECT 1", "mysql", "postgres", validate=False)

    assert first.success is True
    assert second.success is True
    assert first.target_sql == second.target_sql
    assert calls == 1


def test_multistatement_sql_remains_rejected_with_cache_enabled(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", False)
    transpiler = SQLTranspiler()
    transpiler._cache_enabled = True

    first = transpiler.transpile("SELECT 1; SELECT 2", "mysql", "postgres", validate=False)
    second = transpiler.transpile("SELECT 1; SELECT 2", "mysql", "postgres", validate=False)

    assert first.success is False
    assert second.success is False
    assert first.error_code == "VALIDATION_FAILED"
    assert second.error_code == "VALIDATION_FAILED"
    assert first.target_sql is None
    assert second.target_sql is None
