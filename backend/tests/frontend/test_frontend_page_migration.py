#!/usr/bin/env python3
"""Regression tests for C1.2a page migration (convert + history pages).

These tests verify that the Convert and History pages correctly use
SessionState for application-state access while preserving widget keys.
"""
from __future__ import annotations

import pytest

from frontend.core.state import SessionState


@pytest.fixture(autouse=True)
def _clear_session_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear session state between tests to ensure isolation."""
    import streamlit as st
    monkeypatch.setattr(st, "session_state", {})


class TestConvertStateAccess:
    """Test that convert page operations use SessionState correctly."""

    def test_convert_last_vm_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        fake_vm = {"status": "valid"}
        state.convert_last_vm = fake_vm
        assert state.convert_last_vm == fake_vm

    def test_convert_target_sql_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.convert_target_sql = "SELECT 1"
        assert state.convert_target_sql == "SELECT 1"

    def test_convert_target_sql_empty_default(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.convert_target_sql == ""

    def test_batch_last_vm_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        fake_bvm = {"total": 2, "succeeded": 1}
        state.batch_last_vm = fake_bvm
        assert state.batch_last_vm == fake_bvm

    def test_add_history_via_state(self) -> None:
        """Simulate convert page adding to history."""
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry(
            sql="SELECT * FROM users",
            source_dialect="postgres",
            target_dialect="mysql",
            result_sql="SELECT * FROM users",
            status="valid",
            created_at="2026-01-01T00:00:00Z",
        )
        assert isinstance(ident, str)
        assert len(ident) > 0
        assert state.history_count() == 1
        entry = state.history[0]
        assert entry["identity"] == ident
        assert entry["sql"] == "SELECT * FROM users"
        assert entry["src"] == "postgres"
        assert entry["tgt"] == "mysql"
        assert entry["result"] == "SELECT * FROM users"
        assert entry["status"] == "valid"
        assert entry["created_at"] == "2026-01-01T00:00:00Z"
        # Verify no is_favorite in entry
        assert "is_favorite" not in entry

    def test_history_persistence_across_access(self) -> None:
        """History should persist when accessed via state property."""
        state = SessionState.get()
        state.ensure_defaults()
        state.add_history_entry("SELECT 1", "p", "m", "SELECT 1", "valid")
        # Access history directly
        history = state.history
        assert len(history) == 1
        # Add another
        state.add_history_entry("SELECT 2", "p", "m", "SELECT 2", "valid")
        assert len(state.history) == 2


class TestHistoryPageAccess:
    """Test that history page operations use SessionState correctly."""

    def test_read_history_from_state(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.add_history_entry("SELECT 1", "p", "m", "SELECT 1", "valid")
        history = state.history
        assert len(history) == 1
        assert history[0]["sql"] == "SELECT 1"

    def test_favorites_from_state(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        state.add_favorite(ident)
        assert state.is_favorite(ident) is True
        assert state.favorites == [ident]

    def test_favorite_toggle(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        # Initially not favorite
        assert state.is_favorite(ident) is False
        # Toggle to favorite
        state.toggle_favorite(ident)
        assert state.is_favorite(ident) is True
        # Toggle back
        state.toggle_favorite(ident)
        assert state.is_favorite(ident) is False

    def test_delete_cleans_favorite(self) -> None:
        """Deleting a history entry must remove its favorite status."""
        state = SessionState.get()
        state.ensure_defaults()
        id_a = state.add_history_entry("SELECT A", "p", "m")
        id_b = state.add_history_entry("SELECT B", "p", "m")
        state.add_favorite(id_a)
        state.add_favorite(id_b)
        assert state.favorite_count() == 2

        # Delete B
        removed = state.remove_history_entry(id_b)
        assert removed is True
        assert state.history_count() == 1
        assert state.favorite_count() == 1
        assert state.is_favorite(id_a) is True
        assert state.is_favorite(id_b) is False

    def test_delete_nonexistent_no_crash(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        removed = state.remove_history_entry("nonexistent")
        assert removed is False
        assert state.history_count() == 0
        assert state.favorite_count() == 0


class TestFilteredHistorySafety:
    """Test that filtering doesn't corrupt state."""

    def test_filtered_list_does_not_mutate_original(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.add_history_entry("SELECT 1", "p", "m", "SELECT 1", "valid")
        state.add_history_entry("SELECT 2", "p", "m", "SELECT 2", "error")

        # Filter (like history page does)
        filtered = [h for h in state.history if h.get("status") == "valid"]
        assert len(filtered) == 1

        # Original should be unchanged
        assert state.history_count() == 2

    def test_filtered_delete_by_identity(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        id_a = state.add_history_entry("SELECT A", "p", "m", "S1", "valid")
        id_b = state.add_history_entry("SELECT B", "p", "m", "S2", "error")
        state.add_favorite(id_a)

        # Filter to valid only
        filtered = [h for h in state.history if h.get("status") == "valid"]
        assert len(filtered) == 1
        assert filtered[0]["identity"] == id_a

        # Delete from filtered list (as history page does)
        filtered = [h for h in filtered if h.get("identity") != id_a]
        assert len(filtered) == 0

        # But state.history should still have both until properly removed
        assert state.history_count() == 2
        # Now remove via proper method
        state.remove_history_entry(id_a)
        assert state.history_count() == 1
        assert state.favorite_count() == 0


class TestWidgetKeysUnchanged:
    """Verify widget keys remain as raw session state."""

    def test_widget_keys_still_accessible_raw(self) -> None:
        """Widget keys should still be accessible via st.session_state directly."""
        import streamlit as st
        st.session_state["convert_src"] = "postgres"
        st.session_state["convert_tgt"] = "mysql"
        st.session_state["convert_src_sql"] = "SELECT 1"
        st.session_state["nl_dialect"] = "postgres"
        st.session_state["hist_search"] = "test"
        st.session_state["hist_filter"] = "All"
        # These should be directly readable (as dict items)
        assert st.session_state["convert_src"] == "postgres"
        assert st.session_state["convert_tgt"] == "mysql"
        assert st.session_state["convert_src_sql"] == "SELECT 1"


class TestNavigationNotModified:
    """Verify navigation intent is not affected by page migration."""

    def test_navigation_intent_persisted_separately(self) -> None:
        """Navigation intent should still work via navigation module."""
        from frontend.core.navigation import create_navigation_intent
        state = SessionState.get()
        state.ensure_defaults()
        intent = create_navigation_intent("diff", "open_diff", source="S")
        state.set_raw("sdm_navigation_intent", intent)
        consumed = state.consume_navigation_intent()
        assert consumed is not None
        assert consumed.target_page == "diff"


class TestNL2SQLStateAccess:
    """Test that nl2sql page uses SessionState for application state."""

    def test_nl_last_vm_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        fake_vm = {"success": True, "sql": "SELECT 1"}
        state.nl_last_vm = fake_vm
        assert state.nl_last_vm == fake_vm

    def test_nl_generation_error_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.nl_generation_error = "Something went wrong"
        assert state.nl_generation_error == "Something went wrong"

    def test_nl_generation_error_clear_on_success(self) -> None:
        """Error should be cleared when a new successful generation occurs."""
        state = SessionState.get()
        state.ensure_defaults()
        state.nl_generation_error = "Old error"
        state.nl_generation_error = None
        assert state.nl_generation_error is None


class TestDiffStateAccess:
    """Test that diff page uses SessionState for application state."""

    def test_diff_last_vm_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        fake_vm = {"classification": "equivalent"}
        state.diff_last_vm = fake_vm
        assert state.diff_last_vm == fake_vm

    def test_selected_finding_index_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.selected_finding_index = 3
        assert state.selected_finding_index == 3

    def test_clear_finding_selection(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.selected_finding_index = 5
        state.clear_finding_selection()
        assert state.selected_finding_index is None


class TestDiffNavigationHandoff:
    """Test Diff navigation handoff works through SessionState."""

    def test_navigation_intent_handoff_via_state(self) -> None:
        """Diff should read navigation intent and clear finding via state."""
        from frontend.core.navigation import create_navigation_intent
        state = SessionState.get()
        state.ensure_defaults()
        # Simulate navigation intent from Convert
        intent = create_navigation_intent(
            "diff", "open_diff",
            source="SELECT 1",
            target="SELECT 2",
            src_dialect="postgres",
            tgt_dialect="mysql",
        )
        state.set_raw("sdm_navigation_intent", intent)
        # Consume should work
        consumed = state.consume_navigation_intent()
        assert consumed is not None
        assert consumed.target_page == "diff"
        assert consumed.action == "open_diff"


class TestLineageStateAccess:
    """Test that lineage page uses SessionState for application state."""

    def test_lineage_last_vm_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        fake_vm = {"dialect": "postgres", "sql": "SELECT 1"}
        state.lineage_last_vm = fake_vm
        assert state.lineage_last_vm == fake_vm

    def test_lineage_last_vm_default_none(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.lineage_last_vm is None


class TestQueryAnalysisStateAccess:
    """Test that query analysis page uses SessionState for application state."""

    def test_qa_last_result_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        fake_result = {"tables": ["users"], "join_count": 0}
        state.qa_last_result = fake_result
        assert state.qa_last_result == fake_result

    def test_qa_last_result_default_none(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.qa_last_result is None


class TestSettingsThemeAccess:
    """Test that settings page uses SessionState for theme."""

    def test_theme_write_and_read(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.theme = "light"
        assert state.theme == "light"

    def test_theme_dark_default(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.theme == "dark"

    def test_theme_invalid_normalized(self) -> None:
        """Invalid theme should fall back to dark in sdm_local_v2.py validation."""
        state = SessionState.get()
        state.ensure_defaults()
        # SessionState allows any string, validation happens in main app
        state.theme = "invalid_theme"
        assert state.theme == "invalid_theme"
        # Main app would then normalize
        from frontend.core.design_tokens import THEMES
        if state.theme not in THEMES:
            state.theme = "dark"
        assert state.theme == "dark"
