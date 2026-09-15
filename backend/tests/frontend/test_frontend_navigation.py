#!/usr/bin/env python3
"""Navigation contract and command palette tests for SQL Dialect Master v2."""
from __future__ import annotations

import pytest

from frontend.core.navigation import (
    NavigationIntent,
    consume_navigation_intent,
    create_navigation_intent,
    get_pending_intent,
    is_valid_action,
)


class TestNavigationIntent:
    """Test NavigationIntent creation and validation."""

    def test_create_with_target_only(self) -> None:
        intent = create_navigation_intent("convert")
        assert intent.target_page == "convert"
        assert intent.action is None
        assert intent.payload == {}
        assert intent.is_valid

    def test_create_with_action_and_payload(self) -> None:
        intent = create_navigation_intent(
            "diff", "open_diff", source="SELECT 1", dialect="postgres"
        )
        assert intent.target_page == "diff"
        assert intent.action == "open_diff"
        assert intent.get_payload("source") == "SELECT 1"
        assert intent.get_payload("dialect") == "postgres"

    def test_empty_intent_is_invalid(self) -> None:
        intent = NavigationIntent()
        assert not intent.is_valid

    def test_get_payload_with_default(self) -> None:
        intent = create_navigation_intent("convert")
        assert intent.get_payload("sql", "fallback") == "fallback"
        assert intent.get_payload("sql") is None

    def test_has_payload(self) -> None:
        intent = create_navigation_intent("convert", sql="test")
        assert intent.has_payload("sql")
        assert not intent.has_payload("missing")

    def test_bool_conversion(self) -> None:
        assert bool(create_navigation_intent("convert")) is True
        assert bool(NavigationIntent()) is False


class TestIsValidAction:
    """Test action validation per page."""

    def test_valid_conversion_action(self) -> None:
        assert is_valid_action("convert", "open_conversion")
        assert is_valid_action("convert", "new_conversion")

    def test_valid_diff_action(self) -> None:
        assert is_valid_action("diff", "open_diff")
        assert is_valid_action("diff", "select_finding")

    def test_none_action_always_valid(self) -> None:
        assert is_valid_action("convert", None)
        assert is_valid_action("diff", None)

    def test_invalid_action(self) -> None:
        assert not is_valid_action("diff", "open_conversion")
        assert not is_valid_action("history", "open_diff")


class TestPendingState:
    """Test pending state lifecycle (without streamlit)."""

    def test_consumed_intent_returns_none(self) -> None:
        """Second consume should return None."""
        import streamlit as st
        intent = create_navigation_intent("diff", "open_diff", source="S")
        st.session_state.sdm_navigation_intent = intent
        first = consume_navigation_intent()
        second = consume_navigation_intent()
        assert first is not None
        assert second is None

    def test_invalid_intent_returns_none(self) -> None:
        """Invalid intent should be treated as None."""
        import streamlit as st
        st.session_state.sdm_navigation_intent = NavigationIntent()
        result = consume_navigation_intent()
        assert result is None

    def test_get_pending_returns_copy(self) -> None:
        """get_pending should not mutate state."""
        import streamlit as st
        intent = create_navigation_intent("convert", "new_conversion")
        st.session_state.sdm_navigation_intent = intent
        got = get_pending_intent()
        assert got.target_page == "convert"
        # State should still have the intent
        still_there = get_pending_intent()
        assert still_there.target_page == "convert"


class TestCommandPaletteCommands:
    """Test command registry structure."""

    def test_commands_have_required_fields(self) -> None:
        from frontend.ui.command_palette import COMMANDS
        for cmd in COMMANDS:
            assert cmd.label
            assert cmd.description
            assert cmd.category
            assert cmd.action

    def test_commands_map_to_valid_pages(self) -> None:
        from frontend.ui.command_palette import COMMANDS, _action_to_page
        for cmd in COMMANDS:
            page = _action_to_page(cmd.action)
            assert page  # Should map to a non-empty page name

    def test_no_duplicate_actions(self) -> None:
        from frontend.ui.command_palette import COMMANDS
        actions = [c.action for c in COMMANDS]
        assert len(actions) == len(set(actions)), "Duplicate actions found"

    def test_all_categories_present(self) -> None:
        from frontend.ui.command_palette import COMMANDS
        categories = {c.category for c in COMMANDS}
        assert "Workspace" in categories
        assert "Library" in categories
        assert "System" in categories

    def test_command_labels_are_clean(self) -> None:
        """No HTML or script in command labels."""
        from frontend.ui.command_palette import COMMANDS
        for cmd in COMMANDS:
            assert "<" not in cmd.label
            assert ">" not in cmd.label
            assert "script" not in cmd.label.lower()


class TestHandoffIntegrity:
    """Test that handoff payloads are well-structured."""

    def test_conversion_handoff_payload(self) -> None:
        """NL2SQL → Convert should have required keys."""
        intent = create_navigation_intent(
            "convert", "open_conversion",
            sql="SELECT 1", dialect="postgres", origin="nl2sql",
        )
        assert intent.get_payload("sql") == "SELECT 1"
        assert intent.get_payload("dialect") == "postgres"
        assert intent.get_payload("origin") == "nl2sql"

    def test_diff_handoff_payload(self) -> None:
        """Convert → Diff should have all SQL fields."""
        intent = create_navigation_intent(
            "diff", "open_diff",
            source="SELECT *", target="SELECT id",
            src_dialect="postgres", tgt_dialect="mysql",
        )
        assert intent.get_payload("source") == "SELECT *"
        assert intent.get_payload("target") == "SELECT id"
        assert intent.get_payload("src_dialect") == "postgres"
        assert intent.get_payload("tgt_dialect") == "mysql"

    def test_finding_selection_payload(self) -> None:
        """Diff internal should have finding_index."""
        intent = create_navigation_intent(
            "diff", "select_finding", finding_index=3,
        )
        assert intent.has_payload("finding_index")
        assert intent.get_payload("finding_index") == 3

    def test_missing_sql_fallback(self) -> None:
        """Missing SQL in conversion intent should not crash."""
        intent = create_navigation_intent("convert", "open_conversion")
        # No sql payload — consumer should handle gracefully
        assert not intent.has_payload("sql")


class TestSecurity:
    """Test security of navigation-related content."""

    @pytest.mark.parametrize(
        "malicious",
        [
            "<script>alert(1)</script>",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
        ],
    )
    def test_malicious_dialect_name(self, malicious: str) -> None:
        """Malicious dialect names must be safe in intents."""
        from frontend.core.escaping import esc
        escaped = str(esc(malicious))
        assert "<" not in escaped

    def test_navigation_payload_not_executed(self) -> None:
        """Navigation payloads should never contain executable content."""
        intent = create_navigation_intent(
            "convert", "open_conversion",
            sql="<script>alert(1)</script>",
            dialect="postgres",
        )
        # The SQL is stored as data, not executed
        assert intent.get_payload("sql") == "<script>alert(1)</script>"
        # But when displayed, it must be escaped
        from frontend.core.escaping import esc
        assert "<script>" not in str(esc(intent.get_payload("sql")))
