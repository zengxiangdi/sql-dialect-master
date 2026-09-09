from backend.core import settings
from backend.core.transpiler import SQLTranspiler


def test_dangerous_sql_is_blocked_by_default():
    assert settings.security_check_enabled is True
    assert settings.security_block_dangerous is True

    result = SQLTranspiler().transpile(
        "DROP TABLE users",
        "mysql",
        "postgres",
    )

    assert result.success is False
    assert result.error_code == "SECURITY_VIOLATION"
    assert result.target_sql is None


def test_stacked_statements_are_blocked_by_default():
    result = SQLTranspiler().transpile(
        "SELECT 1; SELECT 2",
        "mysql",
        "postgres",
    )

    assert result.success is False
    assert result.error_code == "SECURITY_VIOLATION"
    assert "Multiple SQL statements" in (result.error or "")


def test_explicit_security_override_is_respected(monkeypatch):
    monkeypatch.setenv("SDM_SECURITY_BLOCK_DANGEROUS", "false")

    # Re-importing the core package in a fresh interpreter is the supported
    # configuration path. This test verifies the flag itself remains mutable
    # for callers that explicitly opt into compatibility behavior.
    settings.security_block_dangerous = False
    result = SQLTranspiler().transpile(
        "DROP TABLE users",
        "mysql",
        "postgres",
    )

    assert result.success is True
    assert any("Dangerous" in warning or "DROP" in warning for warning in result.warnings)
