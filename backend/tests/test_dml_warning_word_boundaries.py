from backend.core.transpiler import SQLTranspiler


def test_dml_warnings_require_statement_keyword_boundaries() -> None:
    transpiler = SQLTranspiler()

    assert transpiler._generate_warnings(
        "SELECT updated_at FROM users", "postgres", "mysql"
    ) == []
    assert transpiler._generate_warnings(
        "SELECT deleted_at FROM users", "postgres", "mysql"
    ) == []

    delete_warnings = transpiler._generate_warnings(
        "DELETE FROM users", "postgres", "mysql"
    )
    update_warnings = transpiler._generate_warnings(
        "UPDATE users SET status = 1", "postgres", "mysql"
    )

    assert "⚠️ DELETE without WHERE clause - will delete all rows" in delete_warnings
    assert "⚠️ UPDATE without WHERE clause - will update all rows" in update_warnings


def test_where_identifier_fragment_does_not_suppress_update_warning() -> None:
    warnings = SQLTranspiler()._generate_warnings(
        "UPDATE users SET somewhere = 1", "postgres", "mysql"
    )

    assert "⚠️ UPDATE without WHERE clause - will update all rows" in warnings


def test_real_where_clause_suppresses_dml_warning() -> None:
    transpiler = SQLTranspiler()

    assert transpiler._generate_warnings(
        "UPDATE users SET status = 1 WHERE id = 1", "postgres", "mysql"
    ) == []
    assert transpiler._generate_warnings(
        "DELETE FROM users WHERE id = 1", "postgres", "mysql"
    ) == []
