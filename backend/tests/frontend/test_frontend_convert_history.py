#!/usr/bin/env python3
"""Regression tests for convert-page history entry creation.

P0 bug: `frontend/pages/convert.py::_add_to_history()` called
`datetime.now(UTC)` after importing only `from datetime import UTC`
(`datetime` was never imported), so *every successful conversion* that
reached the history step raised `NameError: name 'datetime' is not
defined`, silently losing the history entry and surfacing a traceback in
the UI.

These tests exercise the real conversion path (SQLTranspiler →
ConversionViewModel → _add_to_history) rather than just the import.
"""
from __future__ import annotations

import pytest
import streamlit as st

from backend.core.transpiler import SQLTranspiler
from frontend.core.design_tokens import DARK
from frontend.core.state import SessionState
from frontend.core.viewmodels import ConversionViewModel
from frontend.pages.convert import _add_to_history


@pytest.fixture(autouse=True)
def _clear_session_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear session state between tests to ensure isolation."""
    monkeypatch.setattr(st, "session_state", {})


def _theme():
    return DARK


def _make_vm(source_sql: str, src: str, tgt: str) -> ConversionViewModel:
    """Real path: transpile with the canonical SQLTranspiler, then adapt."""
    result = SQLTranspiler().transpile(source_sql, src, tgt)
    return ConversionViewModel.from_transpile_result(result)


class TestAddToHistoryRegression:
    """_add_to_history must not raise on a successful conversion."""

    def test_successful_conversion_creates_history_entry(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        vm = _make_vm("SELECT * FROM users", "postgres", "mysql")
        assert vm.status == "valid", "precondition: conversion must succeed for the repro"
        _add_to_history(state, vm, _theme())  # raised NameError before the fix

        assert state.history_count() == 1
        entry = state.history[0]
        assert entry["sql"] == "SELECT * FROM users"
        assert entry["src"] == "postgres"
        assert entry["tgt"] == "mysql"
        assert entry["result"] == vm.target_sql
        assert entry["created_at"], "created_at must be populated (ISO-8601)"

    def test_unsuccessful_conversion_is_not_added(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        # Build a guaranteed failure ViewModel: a security-blocked transpile
        # (dangerous DDL) must simply be skipped by history.
        failed_result = SQLTranspiler().transpile(
            "DROP TABLE users; SELECT 1",
            "postgres",
            "mysql",
        )
        assert not failed_result.success, "precondition: must be a failed conversion"
        vm = ConversionViewModel.from_transpile_result(failed_result)
        assert vm.status == "error"

        _add_to_history(state, vm, _theme())

        assert state.history_count() == 0
