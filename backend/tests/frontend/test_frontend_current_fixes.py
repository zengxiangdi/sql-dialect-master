"""Regression coverage for the current frontend state and input contracts."""
from __future__ import annotations

import sqlglot
import streamlit as st

from frontend.core.navigation import NavigationIntent
from frontend.core.sql_inputs import parse_single_sql
from frontend.core.state import SessionState
from frontend.core.statuses import normalize_status


def test_diff_input_contract_rejects_multiple_statements() -> None:
    try:
        parse_single_sql("SELECT 1; DROP TABLE users", "postgres")
    except sqlglot.errors.ParseError as exc:
        assert "Multiple SQL statements" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("multiple SQL statements must be rejected")


def test_navigation_payload_types_are_validated_at_boundary() -> None:
    assert not NavigationIntent(
        target_page="convert",
        action="open_conversion",
        payload={"sql": 123},
    ).is_valid
    assert NavigationIntent(
        target_page="convert",
        action="open_conversion",
        payload={"sql": "SELECT 1", "dialect": "postgres"},
    ).is_valid


def test_history_fields_and_status_are_normalized() -> None:
    raw: dict[str, object] = {
        "sdm_history": [{
            "identity": "safe",
            "sql": None,
            "src": 123,
            "tgt": None,
            "result_sql": 456,
            "status": "danger",
            "created_at": 789,
        }]
    }
    original = st.session_state
    try:
        st.session_state = raw
        state = SessionState.get()
        state.ensure_defaults()
        entry = state.history[0]
        assert entry["sql"] == ""
        assert entry["src"] == "postgres"
        assert entry["tgt"] == "mysql"
        assert entry["result"] is None
        assert entry["status"] == "error"
        assert entry["created_at"] == ""
    finally:
        st.session_state = original


def test_legacy_status_aliases_share_canonical_vocabulary() -> None:
    assert normalize_status("success") == "valid"
    assert normalize_status("danger") == "error"
    assert normalize_status("pending") == "neutral"
