"""Regression coverage for the backend audit fixes in this release."""

from backend.core.p1_sql_scanner import prepare_sql_for_parser
from backend.core.rules import RuleEngine
from backend.core.semantic_diff import diff_sql_ast


def test_fail_closed_note_filter_removes_both_success_notes_only(monkeypatch):
    import backend.core.transpiler as transpiler_module

    legitimate = "Client note: STRING_AGG and GROUP_CONCAT are both accepted by our warehouse"
    static_success = "STRING_AGG → GROUP_CONCAT transformation"
    rule_success = "Converted STRING_AGG to GROUP_CONCAT"
    fail_closed = transpiler_module.DYNAMIC_SEPARATOR_FAIL_NOTE
    monkeypatch.setattr(
        transpiler_module,
        "get_compatibility_notes",
        lambda _source, _target: [legitimate, static_success, rule_success, fail_closed],
    )

    result = transpiler_module.SQLTranspiler().transpile(
        "SELECT STRING_AGG(name, CONCAT(',', suffix)) FROM users",
        "postgres",
        "mysql",
    )

    assert result.success is False
    assert legitimate in result.compatibility_notes
    assert fail_closed in result.compatibility_notes
    assert static_success not in result.compatibility_notes
    assert rule_success not in result.compatibility_notes


