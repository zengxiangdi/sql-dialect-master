from backend.core.config import settings
from backend.core.transpiler import SQLTranspiler


def test_security_enabled_multiple_statements_keep_security_violation(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", True)
    monkeypatch.setattr(settings, "security_block_dangerous", True)

    result = SQLTranspiler().transpile(
        "SELECT 1; SELECT 2",
        "mysql",
        "postgres",
    )

    assert result.success is False
    assert result.error_code == "SECURITY_VIOLATION"
    assert "Multiple SQL statements detected" in result.error


def test_security_enabled_allow_mode_keeps_validation_failed_for_multiple_statements(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", True)
    monkeypatch.setattr(settings, "security_block_dangerous", False)

    result = SQLTranspiler().transpile(
        "SELECT 1; SELECT 2",
        "mysql",
        "postgres",
    )

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert "Multiple SQL statements are not supported" in result.error


def test_security_disabled_keeps_validation_failed_for_multiple_statements(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", False)

    result = SQLTranspiler().transpile(
        "SELECT 1; SELECT 2",
        "mysql",
        "postgres",
    )

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert "Multiple SQL statements are not supported" in result.error
