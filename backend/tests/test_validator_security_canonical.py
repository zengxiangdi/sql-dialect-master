"""Regression tests for the public security validator adapter."""

import pytest

from backend.core.exceptions import SecurityViolationError
from backend.core.nl2sql_pipeline.dialect import apply_dialect_adjustments
from backend.utils.validators import validate_sql_security


def test_public_validator_ignores_dangerous_words_in_literals_and_comments() -> None:
    sql = "SELECT 'DROP TABLE users; UNION SELECT secret' AS body -- DELETE FROM users"

    safe, warnings = validate_sql_security(sql)

    assert safe is True
    assert warnings == []


def test_public_validator_uses_canonical_blocking_behavior() -> None:
    with pytest.raises(SecurityViolationError, match="Dangerous SQL operation detected"):
        validate_sql_security("DROP TABLE users", block_dangerous=True)


def test_public_validator_ignores_mysql_hash_comments() -> None:
    safe, warnings = validate_sql_security(
        "SELECT 1 # DROP TABLE users; SELECT SLEEP(10)",
        dialect="mysql",
    )

    assert safe is True
    assert warnings == []


def test_public_validator_preserves_warning_mode() -> None:
    safe, warnings = validate_sql_security(
        "UPDATE users SET name = 'x'",
        block_dangerous=False,
    )

    assert safe is False
    assert any("UPDATE without WHERE" in warning for warning in warnings)


def test_mysql_hash_comments_are_not_rewritten() -> None:
    sql = "SELECT DATE_SUB(CURRENT_DATE, 7) AS value # DATE_SUB(CURRENT_DATE, 99)"

    adjusted = apply_dialect_adjustments(sql, "mysql")

    assert "INTERVAL 7 DAY" in adjusted
    assert "DATE_SUB(CURRENT_DATE, 99)" in adjusted
    assert "INTERVAL 99 DAY" not in adjusted
