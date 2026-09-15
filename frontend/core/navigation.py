"""Unified navigation intent system for SQL Dialect Master v2.

Replaces scattered sdm_pending_* session state keys with a single
NavigationIntent dataclass. All cross-page handoffs flow through this
contract:

    Producer → NavigationIntent → session state
                             ↓
    Consumer reads once, clears immediately

Supported actions:
    open_conversion   — NL2SQL / History → Convert
    open_diff         — Convert / NL2SQL → Diff
    select_finding    — Diff internal (finding selection)
    new_conversion    — Command Palette → Convert
    open_lineage      — Command Palette → Lineage
    open_query_analysis  — Command Palette → Query Analysis
    open_history      — Command Palette → History
    open_settings     — Command Palette → Settings
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ActionKind = Literal[
    "open_conversion",
    "open_diff",
    "select_finding",
    "new_conversion",
    "open_lineage",
    "open_query_analysis",
    "open_history",
    "open_settings",
    "open_functions",
    "open_types",
    "open_templates",
    "open_runtime",
]


@dataclass
class NavigationIntent:
    """Single source of truth for cross-page navigation."""

    target_page: str = ""
    action: ActionKind | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    # Validation
    @property
    def is_valid(self) -> bool:
        return bool(self.target_page)

    def has_payload(self, key: str) -> bool:
        return key in self.payload

    def get_payload(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    def __bool__(self) -> bool:
        return self.is_valid


def create_navigation_intent(
    target_page: str,
    action: ActionKind | None = None,
    **payload: Any,
) -> NavigationIntent:
    """Factory for NavigationIntent."""
    return NavigationIntent(
        target_page=target_page,
        action=action,
        payload=payload,
    )


# ── Known actions per page ─────────────────────────────────────────────

PAGE_ACTIONS: dict[str, list[ActionKind]] = {
    "convert": ["open_conversion", "new_conversion"],
    "diff": ["open_diff", "select_finding"],
    "lineage": ["open_lineage"],
    "query_analysis": ["open_query_analysis"],
    "history": ["open_history"],
    "settings": ["open_settings"],
    "functions": ["open_functions"],
    "types": ["open_types"],
    "templates": [],
    "runtime": ["open_runtime"],
    "nl2sql": [],
}


def is_valid_action(target_page: str, action: str | None) -> bool:
    """Check if an action is valid for a given page."""
    if action is None:
        return True
    allowed = PAGE_ACTIONS.get(target_page, [])
    return action in allowed or target_page == "convert"  # open_conversion goes to convert


# ── Session state helpers ──────────────────────────────────────────────

_NAV_KEY = "sdm_navigation_intent"
_FINDING_KEY = "sdm_selected_finding_index"


def get_pending_intent() -> NavigationIntent:
    """Read the current pending navigation intent from session state."""
    import streamlit as st
    raw = st.session_state.get(_NAV_KEY)
    if isinstance(raw, NavigationIntent):
        return raw
    return NavigationIntent()


def consume_navigation_intent() -> NavigationIntent | None:
    """Atomically read and clear the pending navigation intent.

    Returns:
        The consumed NavigationIntent, or None if there was no pending intent.
    """
    import streamlit as st
    intent = get_pending_intent()
    if not intent:
        return None
    st.session_state[_NAV_KEY] = NavigationIntent()
    return intent


def clear_finding_selection() -> None:
    """Clear the selected finding index from session state."""
    import streamlit as st
    st.session_state[_FINDING_KEY] = None
