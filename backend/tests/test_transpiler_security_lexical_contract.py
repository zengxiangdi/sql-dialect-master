import pytest

from backend.core.transpiler import SQLTranspiler


@pytest.fixture
def transpiler() -> SQLTranspiler:
    return SQLTranspiler()


@pytest.mark.parametrize(
    ("sql", "source"),
    [
        ("SELECT 'DROP TABLE users' AS note", "postgres"),
        ("SELECT `DROP` FROM orders", "mysql"),
        ("SELECT [DROP] FROM orders", "tsql"),
        ("SELECT 1 -- DROP TABLE users\n", "postgres"),
        ("SELECT $$DROP TABLE users$$ AS body", "postgres"),
    ],
)
def test_security_ignores_non_executable_dangerous_keywords(
    transpiler: SQLTranspiler, sql: str, source: str
) -> None:
    result = transpiler.transpile(sql, source, "postgres")

    assert result.success is True
    assert result.error_code is None
    assert result.target_sql is not None
    assert result.target_sql.strip()


def test_security_blocks_executable_dangerous_operation(transpiler: SQLTranspiler) -> None:
    result = transpiler.transpile("DROP TABLE users", "postgres", "postgres")

    assert result.success is False
    assert result.error_code == "SECURITY_VIOLATION"
    assert result.error == "Security check failed: Dangerous SQL operation detected: DROP"


def test_security_does_not_warn_for_delete_keyword_inside_literal(transpiler: SQLTranspiler) -> None:
    result = transpiler.transpile(
        "SELECT 'DELETE without WHERE' AS message", "postgres", "postgres"
    )

    assert result.success is True
    assert all("DELETE without WHERE" not in warning for warning in result.warnings)
