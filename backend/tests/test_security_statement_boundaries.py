"""Regression tests for statement-level SQL security validation."""

from backend.core.transpiler import SQLTranspiler
from backend.core.config import settings


def test_stacked_statements_are_detected_structurally(monkeypatch) -> None:
    """Real statement boundaries are detected even when regexes do not match."""
    transpiler = SQLTranspiler()
    monkeypatch.setattr(settings, "security_block_dangerous", True)

    result = transpiler._validate_security(
        "SELECT id FROM users; SELECT name FROM users"
    )

    assert result["blocked"] is True
    assert result["reason"] == "Multiple SQL statements detected"


def test_semicolon_inside_literal_is_not_treated_as_statement_boundary(monkeypatch) -> None:
    """Quoted semicolons remain part of a single parsed statement."""
    transpiler = SQLTranspiler()
    monkeypatch.setattr(settings, "security_block_dangerous", True)

    result = transpiler._validate_security(
        "SELECT 'value;still-one-statement' AS value"
    )

    assert result["blocked"] is False
    assert result["reason"] is None
