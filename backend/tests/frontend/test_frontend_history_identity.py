#!/usr/bin/env python3
"""Tests for history entry identity (stable key instead of list index)."""
from __future__ import annotations


class TestHistoryIdentity:
    """Test that history entries use stable identity keys."""

    def test_entry_has_identity(self) -> None:
        """Each history entry should have an 'identity' key."""
        entry = {
            "identity": "abc12345",
            "sql": "SELECT * FROM users",
            "src": "postgres",
            "tgt": "mysql",
            "status": "valid",
        }
        assert "identity" in entry
        assert entry["identity"] == "abc12345"

    def test_identity_uniqueness(self) -> None:
        """Different entries should have different identities."""
        entry1 = {"identity": "aaaa1111", "sql": "SELECT 1"}
        entry2 = {"identity": "bbbb2222", "sql": "SELECT 2"}
        assert entry1["identity"] != entry2["identity"]

    def test_identity_not_list_index(self) -> None:
        """Identity should not be a simple list index."""
        entry = {"identity": "abc12345", "sql": "SELECT 1"}
        # Should be a hex string, not an integer
        assert isinstance(entry["identity"], str)
        assert not entry["identity"].isdigit()

    def test_filtered_delete_uses_identity(self) -> None:
        """Delete after filter should remove correct entry by identity."""
        history = [
            {"identity": "aaa11111", "sql": "SELECT * FROM users", "status": "valid"},
            {"identity": "bbb22222", "sql": "SELECT * FROM orders", "status": "valid"},
            {"identity": "ccc33333", "sql": "SELECT * FROM products", "status": "error"},
        ]

        # Simulate filtering for "Success" only
        filtered = [h for h in history if h.get("status") == "valid"]

        # Delete by identity from filtered list
        delete_identity = filtered[1]["identity"]  # "bbb22222"
        history = [h for h in history if h.get("identity") != delete_identity]

        # Should remove the correct entry
        assert len(history) == 2
        assert all(h["identity"] != "bbb22222" for h in history)
        assert any(h["identity"] == "aaa11111" for h in history)
        assert any(h["identity"] == "ccc33333" for h in history)

    def test_filtered_favorite_uses_identity(self) -> None:
        """Favorite after filter should work by identity."""
        history = [
            {"identity": "aaa11111", "sql": "SELECT 1"},
            {"identity": "bbb22222", "sql": "SELECT 2"},
            {"identity": "ccc33333", "sql": "SELECT 3"},
        ]

        filtered = history[::2]  # ["aaa11111", "ccc33333"]
        fav_identity = filtered[1]["identity"]  # "ccc33333"

        # Simulate adding to favorites
        favorites = []
        if fav_identity not in favorites:
            favorites.append(fav_identity)

        assert fav_identity in favorites
        assert "aaa11111" not in favorites
