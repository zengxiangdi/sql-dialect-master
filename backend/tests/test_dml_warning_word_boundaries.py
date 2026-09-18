from backend.core.transpiler import SQLTranspiler


def test_dml_warnings_produced_by_security_validator() -> None:
    """DML-without-WHERE warnings come from _validate_security, not _generate_warnings."""
    transpiler = SQLTranspiler()

    # _generate_warnings no longer produces DML-without-WHERE warnings
    assert transpiler._generate_warnings(
        "DELETE FROM users", "postgres", "mysql"
    ) == []
    assert transpiler._generate_warnings(
        "UPDATE users SET status = 1", "postgres", "mysql"
    ) == []

    # But the full transpile should still produce exactly one warning via security
    result = transpiler.transpile("DELETE FROM users", "postgres", "mysql")
    delete_warnings = [w for w in result.warnings if "DELETE" in w and "WHERE" in w]
    assert len(delete_warnings) == 1

    result2 = transpiler.transpile("UPDATE users SET status = 1", "postgres", "mysql")
    update_warnings = [w for w in result2.warnings if "UPDATE" in w and "WHERE" in w]
    assert len(update_warnings) == 1


def test_where_identifier_fragment_does_not_suppress_update_warning() -> None:
    """A column name containing 'where' should not suppress the warning."""
    result = SQLTranspiler().transpile(
        "UPDATE users SET somewhere = 1", "postgres", "mysql"
    )
    update_warnings = [w for w in result.warnings if "UPDATE" in w and "WHERE" in w]
    assert len(update_warnings) == 1


def test_real_where_clause_suppresses_dml_warning() -> None:
    transpiler = SQLTranspiler()

    result1 = transpiler.transpile(
        "UPDATE users SET status = 1 WHERE id = 1", "postgres", "mysql"
    )
    assert not any("UPDATE" in w and "WHERE" in w for w in result1.warnings)

    result2 = transpiler.transpile(
        "DELETE FROM users WHERE id = 1", "postgres", "mysql"
    )
    assert not any("DELETE" in w and "WHERE" in w for w in result2.warnings)
