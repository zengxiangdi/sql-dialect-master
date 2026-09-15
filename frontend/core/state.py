"""Typed frontend state model for SQL Dialect Master v2.

All mutable application state is accessed through this module rather than
scattered raw `st.session_state["key"]` reads across tabs. This centralizes:
- initialization / default values
- namespacing so different workspaces cannot clobber each other
- explicit types for every field
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ── Value objects ──────────────────────────────────────────────────────

StatusKind = Literal["valid", "warning", "error", "info", "neutral"]


@dataclass(frozen=True)
class HistoryEntry:
    """A single conversion kept in history."""

    sql: str
    source_dialect: str
    target_dialect: str
    result_sql: str | None = None
    status: StatusKind = "neutral"
    created_at: str = ""  # ISO-8601, set by caller
    is_favorite: bool = False


@dataclass(frozen=True)
class ConversionState:
    """Ephemeral state for the Convert workspace."""

    source_dialect: str = "postgres"
    target_dialect: str = "mysql"
    source_sql: str = ""
    target_sql: str | None = None
    last_result: Any | None = None  # ConversionViewModel or raw dict
    formatted_source: str | None = None
    batch_source: str = ""
    batch_target: str = "mysql"
    batch_results: list[Any] | None = None


@dataclass(frozen=True)
class NL2SQLState:
    """Ephemeral state for the NL2SQL workspace."""

    target_dialect: str = "postgres"
    natural_language: str = ""
    table_hint: str = ""
    last_result: Any | None = None


@dataclass(frozen=True)
class LineageState:
    """Ephemeral state for the Lineage workspace."""

    dialect: str = "postgres"
    sql: str = ""
    last_tables: list[dict[str, str]] = field(default_factory=list)
    last_output_cols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExplainState:
    """Ephemeral state for the Query Analysis workspace."""

    sql: str = ""
    dialect_a: str = "postgres"
    dialect_b: str = "mysql"
    plan_a: dict[str, Any] | None = None
    plan_b: dict[str, Any] | None = None


@dataclass(frozen=True)
class FunctionsState:
    """Ephemeral state for the Functions library."""

    search_query: str = ""
    category_filter: str = "all"


@dataclass(frozen=True)
class TypesState:
    """Ephemeral state for the Types library."""

    source_dialect: str = "postgres"
    target_dialect: str = "mysql"
    selected_type: str = ""
    category_filter: str = "all"


@dataclass(frozen=True)
class SettingsState:
    """Ephemeral state for the Settings page."""

    theme: Literal["dark", "light"] = "dark"
    keybindings_visible: bool = False


# ── Application-level state container ──────────────────────────────────

@dataclass
class AppState:
    """Top-level application state — one instance per session."""

    theme: Literal["dark", "light"] = "dark"
    history: list[HistoryEntry] = field(default_factory=list)
    favorites: list[int] = field(default_factory=list)  # indices into history
    conversion: ConversionState = field(default_factory=ConversionState)
    nl2sql: NL2SQLState = field(default_factory=NL2SQLState)
    lineage: LineageState = field(default_factory=LineageState)
    explain: ExplainState = field(default_factory=ExplainState)
    functions: FunctionsState = field(default_factory=FunctionsState)
    types: TypesState = field(default_factory=TypesState)
    settings: SettingsState = field(default_factory=SettingsState)

    def current_theme_name(self) -> Literal["dark", "light"]:
        return self.theme

    def history_count(self) -> int:
        return len(self.history)

    def favorite_count(self) -> int:
        return len(self.favorites)
