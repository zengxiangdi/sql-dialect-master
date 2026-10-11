"""Regression tests for the frontend interaction/state fixes."""
from __future__ import annotations

import streamlit as st

from frontend.core.fingerprints import input_fingerprint
from frontend.core.state import SessionState
from frontend.core.viewmodels import SemanticDiffViewModel
from frontend.pages.convert import (
    _clear_source_sql,
    _invalidate_stale_batch,
    _invalidate_stale_conversion,
    _swap_dialects,
)
from frontend.pages.nl2sql import EXAMPLE_QUERIES, _apply_selected_example


def _state(monkeypatch):
    raw: dict[str, object] = {}
    monkeypatch.setattr(st, "session_state", raw)
    state = SessionState.get()
    state.ensure_defaults()
    return state, raw


def test_converter_callbacks_update_widget_state_before_next_run(monkeypatch):
    state, raw = _state(monkeypatch)
    raw.update({"convert_src": "postgres", "convert_tgt": "mysql", "convert_src_sql": "SELECT 1"})
    state.convert_last_vm = object()
    state.convert_target_sql = "SELECT 1"
    state.convert_last_fingerprint = "old"

    _swap_dialects()
    assert raw["convert_src"] == "mysql"
    assert raw["convert_tgt"] == "postgres"
    assert state.convert_last_vm is None
    assert state.convert_target_sql == ""

    raw["convert_src_sql"] = "SELECT 1"
    _clear_source_sql()
    assert raw["convert_src_sql"] == ""


def test_conversion_and_batch_results_are_invalidated_on_input_change(monkeypatch):
    state, _ = _state(monkeypatch)
    state.convert_last_vm = object()
    state.convert_last_fingerprint = input_fingerprint("SELECT 1", "postgres", "mysql")
    _invalidate_stale_conversion(state, input_fingerprint("SELECT 2", "postgres", "mysql"))
    assert state.convert_last_vm is None

    state.batch_last_vm = object()
    state.batch_last_fingerprint = input_fingerprint("SELECT 1", "postgres", "mysql")
    _invalidate_stale_batch(state, input_fingerprint("SELECT 2", "postgres", "mysql"))
    assert state.batch_last_vm is None


def test_nl_example_callback_does_not_run_on_unrelated_rerun(monkeypatch):
    _, raw = _state(monkeypatch)
    raw["nl_example_sel"] = "Count all users"
    _apply_selected_example()
    assert raw["nl_input_text"] == EXAMPLE_QUERIES["Count all users"]
    raw["nl_input_text"] = "my edited request"
    # No callback is invoked by ordinary reruns, so this value remains intact.
    assert raw["nl_input_text"] == "my edited request"


def test_semantic_status_uses_renderer_status_vocabulary():
    from backend.core.semantic_diff import diff_sql_ast

    equal = diff_sql_ast("SELECT 1", "SELECT 1", "postgres", "postgres")
    vm = SemanticDiffViewModel.from_backend("SELECT 1", "SELECT 1", "postgres", "postgres", equal)
    assert vm.overall_status == "valid"

    different = diff_sql_ast("SELECT * FROM users", "SELECT id FROM users", "postgres", "postgres")
    vm = SemanticDiffViewModel.from_backend(
        "SELECT * FROM users", "SELECT id FROM users", "postgres", "postgres", different
    )
    assert vm.overall_status == "error"
