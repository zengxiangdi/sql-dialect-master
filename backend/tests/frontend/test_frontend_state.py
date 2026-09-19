#!/usr/bin/env python3
"""Tests for SessionState contract and legacy state compatibility."""
from __future__ import annotations

import pytest

from frontend.core.state import (
    HistoryEntry,
    SessionState,
)


@pytest.fixture(autouse=True)
def _clear_session_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear session state between tests to ensure isolation."""
    import streamlit as st
    monkeypatch.setattr(st, "session_state", {})


class TestSessionStateInitialization:
    """Test SessionState initialization and defaults."""

    def test_theme_default_is_dark(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.theme == "dark"

    def test_history_default_is_empty_list(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.history == []

    def test_favorites_default_is_empty_list(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.favorites == []
        assert isinstance(state.favorites, list)

    def test_navigation_default_is_empty_intent(self) -> None:
        from frontend.core.navigation import NavigationIntent
        state = SessionState.get()
        state.ensure_defaults()
        intent = state.get_pending_intent()
        assert isinstance(intent, NavigationIntent)
        assert not intent.is_valid

    def test_finding_index_default_is_none(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.selected_finding_index is None

    def test_version_key_set_after_migrate(self) -> None:
        state = SessionState.get()
        state.migrate()
        assert state._raw.get("sdm_state_version") == 1

    def test_ensure_defaults_does_not_set_version(self) -> None:
        """ensure_defaults should not write version key."""
        state = SessionState.get()
        state.ensure_defaults()
        assert "sdm_state_version" not in state._raw

    def test_history_count_empty(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.history_count() == 0

    def test_favorite_count_empty(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.favorite_count() == 0


class TestSessionStateHistory:
    """Test history add/remove via SessionState."""

    def test_add_history_entry(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        identity = state.add_history_entry(
            "SELECT 1", "postgres", "mysql", "SELECT 1;", "valid",
            created_at="2026-01-01T00:00:00+00:00"
        )
        assert isinstance(identity, str)
        assert len(identity) > 0
        assert state.history_count() == 1

    def test_add_history_entry_fields(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.add_history_entry(
            "SELECT * FROM users", "mysql", "postgres",
            "SELECT * FROM users;", "valid",
        )
        entry = state.history[0]
        assert entry["sql"] == "SELECT * FROM users"
        assert entry["src"] == "mysql"
        assert entry["tgt"] == "postgres"
        assert entry["result"] == "SELECT * FROM users;"
        assert entry["status"] == "valid"

    def test_remove_history_entry(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        id1 = state.add_history_entry("SELECT 1", "p", "m")
        id2 = state.add_history_entry("SELECT 2", "p", "m")
        assert state.history_count() == 2
        removed = state.remove_history_entry(id1)
        assert removed is True
        assert state.history_count() == 1
        assert state.history[0]["identity"] == id2

    def test_remove_nonexistent_entry(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        removed = state.remove_history_entry("nonexistent")
        assert removed is False

    def test_remove_cleans_favorite(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        state.add_favorite(ident)
        assert state.is_favorite(ident)
        state.remove_history_entry(ident)
        assert not state.is_favorite(ident)


class TestSessionStateFavorites:
    """Test favorites type contract and operations."""

    def test_favorites_are_str_list(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        state.add_favorite(ident)
        favs = state.favorites
        assert isinstance(favs, list)
        assert len(favs) == 1
        assert isinstance(favs[0], str)

    def test_add_favorite_idempotent(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        state.add_favorite(ident)
        state.add_favorite(ident)
        assert state.favorite_count() == 1

    def test_remove_favorite(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        state.add_favorite(ident)
        state.remove_favorite(ident)
        assert state.favorite_count() == 0

    def test_toggle_favorite(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        state.toggle_favorite(ident)
        assert state.is_favorite(ident)
        state.toggle_favorite(ident)
        assert not state.is_favorite(ident)

    def test_legacy_int_favorites_migrated_to_empty(self) -> None:
        """Int-based favorites must not crash and must migrate safely."""
        state = SessionState.get()
        state._raw["sdm_favorites"] = [1, 2, 3]
        state.migrate()
        assert state.favorites == []

    def test_favorites_setter_rejects_non_list(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        with pytest.raises(TypeError):
            state.favorites = "not a list"  # type: ignore[assignment]

    def test_favorites_setter_rejects_int_items(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        with pytest.raises(TypeError):
            state.favorites = [1, 2, 3]  # type: ignore[list-item]

    def test_favorites_setter_accepts_str_list(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.favorites = ["abc", "def"]
        assert state.favorites == ["abc", "def"]


class TestHistoryEntryContract:
    """Test HistoryEntry dataclass contract."""

    def test_frozen(self) -> None:
        entry = HistoryEntry(
            identity="abc123",
            sql="SELECT 1",
            source_dialect="postgres",
            target_dialect="mysql",
        )
        with pytest.raises((TypeError, AttributeError)):
            entry.sql = "SELECT 2"

    def test_default_status(self) -> None:
        entry = HistoryEntry(
            identity="x", sql="SELECT 1",
            source_dialect="p", target_dialect="m",
        )
        assert entry.status == "neutral"

    def test_with_result(self) -> None:
        entry = HistoryEntry(
            identity="x", sql="SELECT 1",
            source_dialect="p", target_dialect="m",
            result_sql="SELECT 1;",
            status="valid",
        )
        assert entry.result_sql == "SELECT 1;"
        assert entry.status == "valid"

    def test_from_raw_dict_legacy_fields(self) -> None:
        raw = {
            "identity": "test123",
            "sql": "SELECT *",
            "src": "mysql",
            "tgt": "postgres",
            "result": "SELECT *",
            "status": "valid",
            "created_at": "2026-01-01T00:00:00Z",
        }
        entry = HistoryEntry.from_raw_dict(raw)
        assert entry.source_dialect == "mysql"
        assert entry.target_dialect == "postgres"
        assert entry.result_sql == "SELECT *"

    def test_from_raw_dict_canonical_fields(self) -> None:
        raw = {
            "identity": "test456",
            "sql": "SELECT 1",
            "source_dialect": "postgres",
            "target_dialect": "mysql",
            "result_sql": "SELECT 1",
            "status": "valid",
        }
        entry = HistoryEntry.from_raw_dict(raw)
        assert entry.source_dialect == "postgres"
        assert entry.target_dialect == "mysql"
        assert entry.result_sql == "SELECT 1"

    def test_to_raw_dict_mapping(self) -> None:
        entry = HistoryEntry(
            identity="abc",
            sql="SELECT 1",
            source_dialect="postgres",
            target_dialect="mysql",
            result_sql="SELECT 1",
            status="valid",
            created_at="2026-01-01T00:00:00Z",
        )
        raw = entry.to_raw_dict()
        assert raw["identity"] == "abc"
        assert raw["sql"] == "SELECT 1"
        assert raw["src"] == "postgres"
        assert raw["tgt"] == "mysql"
        assert raw["result"] == "SELECT 1"
        assert raw["status"] == "valid"

    def test_missing_identity_gets_generated_in_migration(self) -> None:
        """Entries without identity should get a generated one, not be dropped."""
        state = SessionState.get()
        state._raw["sdm_history"] = [
            {"identity": "good1", "sql": "SELECT 1"},
            {"sql": "SELECT 2"},  # missing identity
            {"identity": "good2", "sql": "SELECT 3"},
        ]
        state.migrate()
        assert len(state.history) == 3
        assert state.history[0]["identity"] == "good1"
        assert state.history[1]["identity"] != ""  # generated
        assert state.history[2]["identity"] == "good2"


class TestMigration:
    """Test state migration behavior."""

    def test_migration_no_op_at_current_version(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state._raw["sdm_state_version"] = 1
        # Should not change anything
        state.migrate()
        assert state._raw["sdm_state_version"] == 1

    def test_migration_adds_version_key(self) -> None:
        state = SessionState.get()
        state._raw.pop("sdm_state_version", None)
        state.migrate()
        assert state._raw["sdm_state_version"] == 1

    def test_migration_leaves_valid_state_untouched(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        state.add_favorite(ident)
        original_history = list(state.history)
        original_favs = list(state.favorites)
        state.migrate()
        assert state.history == original_history
        assert state.favorites == original_favs


class TestNavigationIntegration:
    """Test that SessionState delegates navigation correctly."""

    def test_consume_navigation_intent(self) -> None:
        from frontend.core.navigation import create_navigation_intent
        state = SessionState.get()
        state.ensure_defaults()
        intent = create_navigation_intent("diff", "open_diff", source="S")
        state._raw["sdm_navigation_intent"] = intent
        consumed = state.consume_navigation_intent()
        assert consumed is not None
        assert consumed.target_page == "diff"
        # Second consume should return None
        assert state.consume_navigation_intent() is None

    def test_clear_finding_selection(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.selected_finding_index = 3
        state.clear_finding_selection()
        assert state.selected_finding_index is None


class TestRawAccess:
    """Test raw session state access methods."""

    def test_get_raw_missing_key(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.get_raw("nonexistent_key") is None

    def test_set_raw_and_get_raw(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        state.set_raw("custom_key", "custom_value")
        assert state.get_raw("custom_key") == "custom_value"

    def test_has_raw(self) -> None:
        state = SessionState.get()
        state.ensure_defaults()
        assert state.has_raw("sdm_theme") is True
        assert state.has_raw("nonexistent_key") is False


class TestMigrationOrdering:
    """Test correct migration ordering and initialization sequence."""

    def test_migrate_before_ensure_defaults_detects_legacy_version(self) -> None:
        """Migration must run before ensure_defaults to detect legacy sessions."""
        state = SessionState.get()
        state._raw["sdm_state_version"] = 0
        state._raw["sdm_favorites"] = [1, 2]  # legacy int favorites
        # Migrate first, then ensure defaults
        state.migrate()
        state.ensure_defaults()
        # Migration should have detected version 0 and migrated
        assert state._raw["sdm_state_version"] == 1
        assert state.favorites == []  # legacy ints migrated to empty

    def test_ensure_defaults_does_not_write_version(self) -> None:
        """ensure_defaults must not write version key."""
        state = SessionState.get()
        state._raw["sdm_state_version"] = 0
        state.ensure_defaults()
        # Version should still be 0 after ensure_defaults
        assert state._raw["sdm_state_version"] == 0

    def test_migration_sets_version_after_processing(self) -> None:
        """migrate must set version at the end."""
        state = SessionState.get()
        state._raw["sdm_state_version"] = 0
        state.migrate()
        assert state._raw["sdm_state_version"] == 1


class TestHistoryIdentityMigration:
    """Test that missing identities are generated, not dropped."""

    def test_missing_identity_gets_generated(self) -> None:
        """Entries without identity should get a generated one."""
        state = SessionState.get()
        state._raw["sdm_history"] = [
            {"sql": "SELECT 1", "src": "p", "tgt": "m"},  # no identity
            {"identity": "abc", "sql": "SELECT 2"},
        ]
        state.migrate()
        assert len(state.history) == 2
        assert state.history[0]["identity"] != ""
        assert state.history[1]["identity"] == "abc"

    def test_malformed_history_entries_dropped(self) -> None:
        """Non-dict entries should be dropped, not crash."""
        state = SessionState.get()
        state._raw["sdm_history"] = [
            "not a dict",  # malformed
            {"identity": "valid", "sql": "SELECT 1"},
        ]
        state.migrate()
        assert len(state.history) == 1
        assert state.history[0]["identity"] == "valid"

    def test_empty_identity_treated_as_missing(self) -> None:
        """Empty string identity should be regenerated."""
        state = SessionState.get()
        state._raw["sdm_history"] = [
            {"identity": "", "sql": "SELECT 1"},
        ]
        state.migrate()
        assert state.history[0]["identity"] != ""

    def test_no_duplicate_identities_in_migration(self) -> None:
        """Generated identities must be unique within a migration run."""
        state = SessionState.get()
        state._raw["sdm_history"] = [
            {"sql": "SELECT 1"},
            {"sql": "SELECT 2"},
            {"sql": "SELECT 3"},
        ]
        state.migrate()
        identities = [e["identity"] for e in state.history]
        assert len(identities) == len(set(identities))


class TestMalformedStateHandling:
    """Test that malformed state doesn't crash the app."""

    def test_none_favorites_migrated_to_empty_list(self) -> None:
        state = SessionState.get()
        state._raw["sdm_favorites"] = None
        state.migrate()
        assert state.favorites == []

    def test_string_favorites_migrated_to_empty_list(self) -> None:
        state = SessionState.get()
        state._raw["sdm_favorites"] = "not a list"
        state.migrate()
        assert state.favorites == []

    def test_dict_favorites_migrated_to_empty_list(self) -> None:
        state = SessionState.get()
        state._raw["sdm_favorites"] = {"not": "a list"}
        state.migrate()
        assert state.favorites == []

    def test_mixed_type_favorites_handled(self) -> None:
        """Favorites with mixed types should be cleaned."""
        state = SessionState.get()
        state._raw["sdm_favorites"] = ["valid", 123, "also_valid"]
        state.migrate()
        # Should keep only string items or clean to empty
        favs = state.favorites
        assert all(isinstance(f, str) for f in favs)

    def test_history_with_none_entries(self) -> None:
        state = SessionState.get()
        state._raw["sdm_history"] = [None, {"identity": "valid"}]
        state.migrate()
        assert len(state.history) == 1

    def test_favorite_not_in_history_is_safe(self) -> None:
        """Orphaned favorite (identity not in history) should not crash."""
        state = SessionState.get()
        state.ensure_defaults()
        state._raw["sdm_favorites"] = ["orphan_identity"]
        assert state.is_favorite("orphan_identity") is True
        # Deleting history entry should not affect orphaned favorite
        removed = state.remove_history_entry("orphan_identity")
        assert removed is False  # entry doesn't exist
        assert state.is_favorite("orphan_identity") is True  # still favorite

    def test_duplicate_identity_in_history_handled(self) -> None:
        """Duplicate identities in history should be preserved (user's choice)."""
        state = SessionState.get()
        state._raw["sdm_history"] = [
            {"identity": "dup", "sql": "SELECT 1"},
            {"identity": "dup", "sql": "SELECT 2"},
        ]
        state.migrate()
        # Should preserve both, not deduplicate
        assert len(state.history) == 2


class TestSingleSourceOfTruth:
    """Test that favorites use single source of truth."""

    def test_is_favorite_not_persisted_on_entry(self) -> None:
        """HistoryEntry should not persist is_favorite."""
        entry = HistoryEntry(
            identity="test",
            sql="SELECT 1",
            source_dialect="p",
            target_dialect="m",
        )
        raw = entry.to_raw_dict()
        assert "is_favorite" not in raw

    def test_add_history_entry_no_favorite_flag(self) -> None:
        """add_history_entry should not set is_favorite."""
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        entry = state.history[0]
        assert "is_favorite" not in entry

    def test_favorite_status_computed_from_list(self) -> None:
        """is_favorite should be computed from favorites list."""
        state = SessionState.get()
        state.ensure_defaults()
        ident = state.add_history_entry("SELECT 1", "p", "m")
        assert state.is_favorite(ident) is False
        state.add_favorite(ident)
        assert state.is_favorite(ident) is True
        state.remove_favorite(ident)
        assert state.is_favorite(ident) is False


class TestFutureVersionHandling:
    """Test handling of future/unknown state versions."""

    def test_unknown_version_is_safe(self) -> None:
        """Unknown future version should not crash."""
        state = SessionState.get()
        state._raw["sdm_state_version"] = 99
        state.migrate()
        # Should not modify state or crash
        assert state._raw["sdm_state_version"] == 99
        assert state.favorites == []
        assert state.history == []

    def test_version_2_skips_migration(self) -> None:
        """Future version should skip migration (no-op)."""
        state = SessionState.get()
        state._raw["sdm_state_version"] = 2
        original_favs = ["a", "b"]
        state._raw["sdm_favorites"] = original_favs
        state.migrate()
        # Should preserve future version and data
        assert state._raw["sdm_state_version"] == 2
        assert state.favorites == original_favs


class TestMigrationIdempotence:
    """Test that repeated migrations are safe."""

    def test_repeated_migration_no_op(self) -> None:
        state = SessionState.get()
        state._raw["sdm_state_version"] = 1
        ident = state.add_history_entry("SELECT 1", "p", "m")
        state.add_favorite(ident)
        original_history = list(state.history)
        original_favs = list(state.favorites)
        # Run migration multiple times
        for _ in range(3):
            state.migrate()
        assert state.history == original_history
        assert state.favorites == original_favs

    def test_migration_after_ensure_defaults_is_no_op(self) -> None:
        """Migration after ensure_defaults should be safe (version already set)."""
        state = SessionState.get()
        state.migrate()  # Sets version to 1
        original_version = state._raw["sdm_state_version"]
        state.ensure_defaults()
        state.migrate()  # Should be no-op
        assert state._raw["sdm_state_version"] == original_version
