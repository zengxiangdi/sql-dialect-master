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
    parse_calls = 0

    def spy_parse(*args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return []

    monkeypatch.setattr("backend.core.transpiler.sqlglot.parse", spy_parse)

    assert SQLTranspiler._has_multiple_statements("SELECT 1") is False
    assert parse_calls == 0
