from backend.core.transpiler import SQLTranspiler


def test_transpile_normalizes_dialect_whitespace_and_case() -> None:
    transpiler = SQLTranspiler()

    result = transpiler.transpile(
        "SELECT 1",
        " MySQL ",
        " POSTGRES ",
    )

    assert result.success is True
    assert result.source_dialect == "mysql"
    assert result.target_dialect == "postgres"
