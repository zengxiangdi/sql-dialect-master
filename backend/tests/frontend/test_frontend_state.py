#!/usr/bin/env python3
"""Frontend state isolation tests."""
from __future__ import annotations

import pytest

from frontend.core.state import (
    AppState,
    ConversionState,
    NL2SQLState,
    LineageState,
    ExplainState,
    FunctionsState,
    TypesState,
    SettingsState,
    HistoryEntry,
)


class TestAppState:
    """Test AppState initialization and defaults."""

    def test_default_state(self) -> None:
        """Default state should have sensible defaults."""
        state = AppState()
        assert state.theme == "dark"
        assert state.history == []
        assert state.favorites == []
        assert state.conversion.source_dialect == "postgres"
        assert state.conversion.target_dialect == "mysql"
        assert state.nl2sql.target_dialect == "postgres"
        assert state.lineage.dialect == "postgres"
        assert state.explain.dialect_a == "postgres"
        assert state.explain.dialect_b == "mysql"

    def test_history_count(self) -> None:
        """history_count should return len(history)."""
        state = AppState()
        assert state.history_count() == 0

        state.history.append(HistoryEntry(sql="SELECT 1", source_dialect="postgres", target_dialect="mysql"))
        assert state.history_count() == 1

    def test_favorite_count(self) -> None:
        """favorite_count should return len(favorites)."""
        state = AppState()
        assert state.favorite_count() == 0

        state.favorites = [0, 1, 2]
        assert state.favorite_count() == 3


class TestConversionState:
    """Test ConversionState defaults."""

    def test_defaults(self) -> None:
        """ConversionState should have sensible defaults."""
        state = ConversionState()
        assert state.source_dialect == "postgres"
        assert state.target_dialect == "mysql"
        assert state.source_sql == ""
        assert state.target_sql is None
        assert state.last_result is None
        assert state.formatted_source is None
        assert state.batch_source == ""
        assert state.batch_target == "mysql"
        assert state.batch_results is None


class TestNL2SQLState:
    """Test NL2SQLState defaults."""

    def test_defaults(self) -> None:
        """NL2SQLState should have sensible defaults."""
        state = NL2SQLState()
        assert state.target_dialect == "postgres"
        assert state.natural_language == ""
        assert state.table_hint == ""
        assert state.last_result is None


class TestHistoryEntry:
    """Test HistoryEntry dataclass."""

    def test_frozen(self) -> None:
        """HistoryEntry should be immutable."""
        entry = HistoryEntry(
            sql="SELECT 1",
            source_dialect="postgres",
            target_dialect="mysql",
        )
        with pytest.raises((TypeError, AttributeError)):
            entry.sql = "SELECT 2"

    def test_default_status(self) -> None:
        """Default status should be neutral."""
        entry = HistoryEntry(sql="SELECT 1", source_dialect="postgres", target_dialect="mysql")
        assert entry.status == "neutral"

    def test_with_result(self) -> None:
        """HistoryEntry should store result SQL."""
        entry = HistoryEntry(
            sql="SELECT 1",
            source_dialect="postgres",
            target_dialect="mysql",
            result_sql="SELECT 1;",
            status="valid",
        )
        assert entry.result_sql == "SELECT 1;"
        assert entry.status == "valid"


class TestStateIsolation:
    """Test that different workspace states don't interfere."""

    def test_conversion_and_nl2sql_independent(self) -> None:
        """Conversion and NL2SQL states should be independent."""
        from dataclasses import replace
        state = AppState()
        state = replace(state, conversion=ConversionState(source_dialect="postgres"))
        state = replace(state, nl2sql=NL2SQLState(target_dialect="mysql"))
        assert state.conversion.source_dialect == "postgres"
        assert state.nl2sql.target_dialect == "mysql"

    def test_history_and_favorites_independent(self) -> None:
        """History and favorites should be independent."""
        state = AppState()
        state.history.append(HistoryEntry(sql="SELECT 1", source_dialect="p", target_dialect="m"))
        state.favorites.append(0)
        assert len(state.history) == 1
        assert len(state.favorites) == 1
