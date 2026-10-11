"""Regression tests for static-analysis workspace boundaries."""
from __future__ import annotations

import pytest
import sqlglot
import streamlit as st

from frontend.core.state import SessionState
from frontend.pages.lineage import _build_lineage, _build_mermaid
from frontend.pages.query_analysis import _analyze_sql


def test_query_analysis_detects_aggregate_without_group_by() -> None:
    result = _analyze_sql("SELECT COUNT(*) FROM users", "postgres")
    assert result["has_aggregation"] is True


def test_query_analysis_rejects_multiple_statements() -> None:
    with pytest.raises(sqlglot.errors.ParseError, match="Multiple SQL statements"):
        _analyze_sql("SELECT 1; SELECT 2", "postgres")


def test_lineage_preserves_self_join_aliases_and_unique_mermaid_ids() -> None:
    vm = _build_lineage(
        "SELECT e.name AS employee, m.name AS manager "
        "FROM employees e LEFT JOIN employees m ON e.manager_id = m.id",
        "postgres",
    )
    assert {(table.name, table.alias) for table in vm.tables} == {
        ("employees", "e"),
        ("employees", "m"),
    }
    mermaid = _build_mermaid(vm)
    assert mermaid.count("table_0[") == 1
    assert mermaid.count("table_1[") == 1
    assert mermaid.count("column_0[") == 1
    assert mermaid.count("column_1[") == 1


def test_history_state_is_bounded_and_repairs_invalid_entries(monkeypatch) -> None:
    raw: dict[str, object] = {"sdm_history": None}
    monkeypatch.setattr(st, "session_state", raw)
    state = SessionState.get()
    state.ensure_defaults()
    assert state.history == []

    raw["sdm_history"] = [None, {"identity": "contains space", "sql": "SELECT 1"}]
    state.ensure_defaults()
    assert len(state.history) == 1
    assert " " not in state.history[0]["identity"]

    raw["sdm_history"] = [{"identity": f"entry-{i}", "sql": str(i)} for i in range(101)]
    state.ensure_defaults()
    assert len(state.history) == 100
    assert state.history[0]["sql"] == "1"
