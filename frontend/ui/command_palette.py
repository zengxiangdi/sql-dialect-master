"""Command Palette for SQL Dialect Master v2.

Provides a button-based command palette for quick access to all workspace actions.
All commands produce NavigationIntent objects — no direct routing.

Note: Streamlit does not support native keyboard shortcuts, so the ⌘K button
is used as the trigger instead of a keyboard listener.
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from frontend.core.design_tokens import ColorTokens
from frontend.core.navigation import create_navigation_intent


@dataclass(frozen=True)
class Command:
    """A single command in the palette."""

    label: str
    description: str
    category: str
    action: str
    shortcut: str = ""


# ── Command registry ──────────────────────────────────────────────────

COMMANDS: list[Command] = [
    # Workspace
    Command("Convert SQL", "Open the SQL conversion workspace", "Workspace", "new_conversion", ""),
    Command("NL2SQL", "Generate SQL from natural language", "Workspace", "open_nl2sql", ""),
    Command("Semantic Diff", "Compare two SQL statements", "Workspace", "open_diff", ""),
    Command("Lineage", "Visualize table dependencies", "Workspace", "open_lineage", ""),
    Command("Runtime", "Execute and verify SQL against databases", "Workspace", "open_runtime", ""),
    # Library
    Command("Function Library", "Search and compare SQL functions", "Library", "open_functions", ""),
    Command("Type Mapping", "Compare data types across dialects", "Library", "open_types", ""),
    Command("Templates", "Browse SQL templates by category", "Library", "open_templates", ""),
    Command("History", "View recent conversions", "Library", "open_history", ""),
    # System
    Command("Query Analysis", "Static analysis of SQL queries", "System", "open_query_analysis", ""),
    Command("Settings", "Theme and configuration", "System", "open_settings", ""),
]

CATEGORY_ORDER = ["Workspace", "Library", "System"]


def render_command_palette(theme: ColorTokens) -> None:
    """Render the command palette overlay."""
    # Check for keyboard shortcut (⌘K / Ctrl+K)
    # Streamlit doesn't support direct key listeners, so we use a text input
    # as the palette trigger. The actual keyboard shortcut is documented.

    # Palette trigger button in topbar
    if st.button("⌘K", key="cmd_palette_trigger", help="Open command palette",
                  use_container_width=False):
        _show_palette(theme)


def _show_palette(theme: ColorTokens) -> None:
    """Show the command palette modal."""
    query = st.text_input(
        "Search commands...",
        key="cmd_palette_query",
        placeholder="Type a command name...",
        label_visibility="collapsed",
    )

    # Filter commands
    q = query.lower().strip()
    if q:
        filtered = [
            c for c in COMMANDS
            if q in c.label.lower() or q in c.description.lower() or q in c.category.lower()
        ]
    else:
        # Group by category
        filtered = list(COMMANDS)

    # Render results
    if not filtered:
        st.caption("No commands found.")
        return

    # Group by category
    groups: dict[str, list[Command]] = {}
    for cmd in filtered:
        if cmd.category not in groups:
            groups[cmd.category] = []
        groups[cmd.category].append(cmd)

    for cat in CATEGORY_ORDER:
        if cat not in groups:
            continue
        st.markdown(
            f'<div style="font-size:10px; font-weight:600; letter-spacing:0.08em; '
            f'text-transform:uppercase; color:{theme.text_muted}; margin:8px 0 4px;">'
            f'{cat}</div>',
            unsafe_allow_html=True,
        )
        for cmd in groups[cat]:
            _render_command_item(cmd, theme)


def _render_command_item(cmd: Command, theme: ColorTokens) -> None:
    """Render a single command item."""
    col_cmd, col_shortcut = st.columns([5, 1])

    with col_cmd:
        clicked = st.button(
            f"**{cmd.label}**\n{cmd.description}",
            key=f"cmd_{cmd.action}",
            use_container_width=True,
            help=f"{cmd.label} — {cmd.description}",
        )
        if clicked:
            _execute_command(cmd)

    with col_shortcut:
        if cmd.shortcut:
            st.caption(cmd.shortcut)


def _execute_command(cmd: Command) -> None:
    """Execute a command by creating and storing a NavigationIntent."""
    intent = create_navigation_intent(
        target_page=_action_to_page(cmd.action),
        action=cmd.action,
    )
    st.session_state.sdm_navigation_intent = intent
    st.rerun()


def _action_to_page(action: str) -> str:
    """Map action to target page."""
    mapping = {
        "new_conversion": "convert",
        "open_nl2sql": "nl2sql",
        "open_diff": "diff",
        "open_lineage": "lineage",
        "open_runtime": "runtime",
        "open_functions": "functions",
        "open_types": "types",
        "open_templates": "templates",
        "open_history": "history",
        "open_query_analysis": "query_analysis",
        "open_settings": "settings",
    }
    return mapping.get(action, "convert")
