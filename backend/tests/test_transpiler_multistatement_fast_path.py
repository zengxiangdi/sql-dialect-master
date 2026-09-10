import pytest

from backend.core.transpiler import SQLTranspiler


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("SELECT 1", False),
        ("SELECT ';' AS value", False),
        ("SELECT 1 -- ; not a separator", False),
        ('SELECT ";" AS value', False),
        ("SELECT 1; SELECT 2", True),
        ("SELECT ';' AS value; SELECT 2", True),
    ],
)
def test_has_multiple_statements_preserves_semicolon_boundaries(sql, expected):
    assert SQLTranspiler._has_multiple_statements(sql) is expected


def test_has_multiple_statements_skips_parser_without_semicolon(monkeypatch):
    """A statement with no separator must not invoke the SQL parser."""
    parse_calls = 0

    def spy_parse(*args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return []

    monkeypatch.setattr("backend.core.transpiler.sqlglot.parse", spy_parse)

    assert SQLTranspiler._has_multiple_statements("SELECT 1") is False
    assert parse_calls == 0


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT ';' AS value",
        "SELECT 1 -- ; not a separator",
        'SELECT ";" AS value',
    ],
)
def test_validate_security_skips_parser_without_executable_separator(monkeypatch, sql):
    """Security validation must reuse scanner boundaries before parsing."""
    parse_calls = 0

    def spy_parse(*args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        raise AssertionError("sqlglot.parse() should not run without an executable separator")

    monkeypatch.setattr("backend.core.transpiler.sqlglot.parse", spy_parse)

    result = SQLTranspiler()._validate_security(sql)

    assert result["multiple_statements"] is False
    assert parse_calls == 0


def test_validate_security_still_parses_executable_multi_statement(monkeypatch):
    """Executable separators retain parser-backed multi-statement detection."""
    parse_calls = 0

    def spy_parse(*args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return [object(), object()]

    monkeypatch.setattr("backend.core.transpiler.sqlglot.parse", spy_parse)

    result = SQLTranspiler()._validate_security("SELECT 1; SELECT 2")

    assert result["multiple_statements"] is True
    assert parse_calls == 1
