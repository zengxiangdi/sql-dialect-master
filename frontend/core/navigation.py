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
    "open_nl2sql",
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
        if not isinstance(self.target_page, str) or not self.target_page:
            return False
        if self.target_page not in PAGE_ACTIONS:
            return False
        if self.action is not None and (
            not isinstance(self.action, str) or not is_valid_action(self.target_page, self.action)
        ):
            return False
        if not isinstance(self.payload, dict):
            return False
        # Payloads are data handed to Streamlit widgets. Validate their shape
        # at the boundary so malformed/stale session state cannot crash a page.
        string_keys = {
            "sql", "source", "target", "dialect", "target_dialect",
            "src_dialect", "tgt_dialect", "origin",
        }
        if any(key in self.payload and not isinstance(self.payload[key], str) for key in string_keys):
            return False
        if self.action == "open_conversion" and not self.payload.get("sql", "").strip():
            return False
        from backend.core.config import SUPPORTED_DIALECTS

        for key in ("dialect", "target_dialect", "src_dialect", "tgt_dialect"):
            if key in self.payload and self.payload[key] not in SUPPORTED_DIALECTS:
                return False
        if "finding_index" in self.payload and (
            not isinstance(self.payload["finding_index"], int)
            or isinstance(self.payload["finding_index"], bool)
            or self.payload["finding_index"] < 0
        ):
            return False
        return True

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


def create_diff_navigation_intent(
    source_sql: str,
    target_sql: str,
    src_dialect: str,
    tgt_dialect: str,
) -> NavigationIntent:
    """Build the Semantic Diff handoff payload from a conversion result.

    The SOURCE is the user's original SQL and the TARGET is the real
    conversion output — the two are never assumed equal.  Callers with
    no original SQL must not use this helper to self-compare.
    """
    return create_navigation_intent(
        target_page="diff",
        action="open_diff",
        source=source_sql,
        target=target_sql,
        src_dialect=src_dialect,
        tgt_dialect=tgt_dialect,
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
    "templates": ["open_templates"],
    "runtime": ["open_runtime"],
    "nl2sql": ["open_nl2sql"],
}


def is_valid_action(target_page: str, action: str | None) -> bool:
    """Check if an action is valid for a given page."""
    if action is None:
        return True
    allowed = PAGE_ACTIONS.get(target_page, [])
    return action in allowed


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
    st.session_state[_NAV_KEY] = NavigationIntent()
    if not intent:
        return None
    return intent


def clear_finding_selection() -> None:
    """Clear the selected finding index from session state."""
    import streamlit as st
    st.session_state[_FINDING_KEY] = None
