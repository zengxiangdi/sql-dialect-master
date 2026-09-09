import sqlglot

from backend.core.transpiler import SQLTranspiler


def test_validate_output_falls_back_to_generic_parser(monkeypatch):
    transpiler = SQLTranspiler()
    calls = []

    def fake_parse_one(sql, read=None, **kwargs):
        calls.append(read)
        if read == "postgres":
            raise ValueError("simulated target parser limitation")
        return object()

    monkeypatch.setattr(sqlglot, "parse_one", fake_parse_one)

    error, warning = transpiler._validate_output_detailed(
        "SELECT 1", "postgres"
    )

    assert error is None
    assert warning is not None
    assert "generic SQL parser accepted" in warning
    assert calls == ["postgres", None]
    assert transpiler._validate_output("SELECT 1", "postgres") is None


def test_validate_output_fails_when_target_and_generic_parser_reject(monkeypatch):
    transpiler = SQLTranspiler()

    def always_fail(*args, **kwargs):
        raise ValueError("invalid SQL")

    monkeypatch.setattr(sqlglot, "parse_one", always_fail)

    error, warning = transpiler._validate_output_detailed("SELECT FROM", "postgres")

    assert error is not None
    assert warning is None
