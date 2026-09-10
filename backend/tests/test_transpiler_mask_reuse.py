from backend.core.config import settings
from backend.core.transpiler import SQLTranspiler


def test_security_and_warning_paths_reuse_masked_sql(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", True)
    monkeypatch.setattr(settings, "security_block_dangerous", False)

    transpiler = SQLTranspiler()
    masked_inputs = []
    original_warning_path = transpiler._generate_warnings_masked

    def spy_warning_path(masked_sql, source, target):
        masked_inputs.append(masked_sql)
        return original_warning_path(masked_sql, source, target)

    monkeypatch.setattr(transpiler, "_generate_warnings_masked", spy_warning_path)
    monkeypatch.setattr(
        transpiler,
        "_generate_warnings",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("security-enabled transpile must reuse masked SQL")
        ),
    )

    result = transpiler.transpile("SELECT 'DROP TABLE users' FROM users", "mysql", "postgres")

    assert result.success is True
    assert len(masked_inputs) == 1
    assert "DROP TABLE users" not in masked_inputs[0]
    assert "SELECT" in masked_inputs[0]


def test_security_helpers_expose_and_consume_masked_sql_contract():
    transpiler = SQLTranspiler()

    security_result = transpiler._validate_security("SELECT 'DROP TABLE users'")
    masked_sql = security_result["executable_sql"]

    assert masked_sql is not None
    assert "DROP TABLE users" not in masked_sql
    assert masked_sql.startswith("SELECT ")
    assert transpiler._generate_warnings("SELECT 'DROP TABLE users'", "mysql", "postgres") == []
