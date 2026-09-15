"""Navigation sidebar for SQL Dialect Master v2.

Defines the three-tier IA (Workspace / Library / System) and renders
a professional navigation sidebar matching the v2 product vision.
"""
from __future__ import annotations

import streamlit as st

from frontend.core.design_tokens import DARK, ColorTokens

# ── Navigation definition ─────────────────────────────────────────────

PAGE_DEFINITIONS = [
    # Workspace
    {"id": "convert", "label": "Convert", "group": "workspace", "icon": "⟷"},
    {"id": "nl2sql",   "label": "NL2SQL",  "group": "workspace", "icon": "💬"},
    {"id": "diff",     "label": "Diff",    "group": "workspace", "icon": "◈"},
    {"id": "lineage",  "label": "Lineage", "group": "workspace", "icon": "⌇"},
    {"id": "runtime",  "label": "Runtime", "group": "workspace", "icon": "▶"},
    # Library
    {"id": "functions","label": "Functions","group": "library", "icon": "ƒ"},
    {"id": "types",    "label": "Types",   "group": "library", "icon": "T"},
    {"id": "templates","label": "Templates","group": "library", "icon": "▤"},
    {"id": "history",  "label": "History", "group": "library", "icon": "◷"},
    # System
    {"id": "settings", "label": "Settings","group": "system",  "icon": "⚙"},
    {"id": "diagnostics","label":"Diagnostics","group":"system","icon":"◉"},
]

GROUP_LABELS = {
    "workspace": "WORKSPACE",
    "library":   "LIBRARY",
    "system":    "SYSTEM",
}


def render_navigation(current_page: str, theme: ColorTokens) -> None:
    """Render the left sidebar navigation.

    Args:
        current_page: The ID of the currently active page
        theme: Active ColorTokens
    """
    # App title
    st.markdown(
        f"""
        <div style="padding: 0 16px 16px; border-bottom: 1px solid {theme.border};">
            <div style="font-size: 11px; font-weight: 700; letter-spacing: 0.12em;
                        text-transform: uppercase; color: {theme.text_muted};">
                SQL Dialect Master
            </div>
            <div style="font-size: 10px; color: {theme.text_muted}; margin-top: 2px;
                        font-family: monospace;">
                v2.0 · Developer Workspace
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # Render groups
    for group_id, group_label in GROUP_LABELS.items():
        items = [p for p in PAGE_DEFINITIONS if p["group"] == group_id]
        if not items:
            continue

        st.markdown(
            f'<div style="font-size: 10px; font-weight: 600; letter-spacing: 0.08em; '
            f'text-transform: uppercase; color: {theme.text_muted}; '
            f'padding: 8px 16px 4px;">{group_label}</div>',
            unsafe_allow_html=True,
        )

        for item in items:
            active = "active" if current_page == item["id"] else ""
            bg = theme.selected_bg if active else "transparent"
            color = theme.accent if active else theme.text_secondary

            st.markdown(
                f"""
                <div class="sdm-nav-item {'sdm-nav-item-active' if active else ''}"
                     data-page="{item['id']}"
                     style="display:flex; align-items:center; gap:10px; padding:7px 16px;
                            font-size:13px; font-weight:{'600' if active else '500'};
                            color:{color}; cursor:pointer;
                            border-left:2px solid {'transparent' if not active else theme.accent};
                            background:{bg}; transition:all 0.15s;">
                    <span style="font-size:14px; width:18px; text-align:center;">{item['icon']}</span>
                    <span>{item['label']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Handle click via Streamlit query params
            if st.button("🕵️", key=f"nav_{item['id']}", help=item["label"],
                         use_container_width=False):
                st.query_params["page"] = item["id"]
                st.rerun()

    # Theme switcher at bottom
    st.markdown("---")
    _render_theme_selector(theme)


def _render_theme_selector(theme: ColorTokens) -> None:
    """Render theme toggle in sidebar."""
    is_dark = theme == DARK

    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:8px; padding:8px 16px;">
            <span style="font-size:12px; color:{theme.text_muted};">Theme:</span>
            <select id="sdm-theme-select"
                    style="background:{theme.input_bg}; color:{theme.text_primary};
                           border:1px solid {theme.border}; border-radius:4px;
                           padding:4px 8px; font-size:12px; cursor:pointer;">
                <option value="dark" {'selected' if is_dark else ''}>Dark</option>
                <option value="light" {'selected' if not is_dark else ''}>Light</option>
            </select>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # JavaScript to handle theme switching
    js = """
    <script>
    (function() {
        const select = document.getElementById('sdm-theme-select');
        if (!select) return;
        select.addEventListener('change', function() {
            window.parent.postMessage({type: 'sdm_theme', value: this.value}, '*');
        });
    })();
    </script>
    """
    st.markdown(js, unsafe_allow_html=True)

    # Catch the message from JS via session state
    if "sdm_theme_message" not in st.session_state:
        st.session_state.sdm_theme_message = None

    # We use a hidden button approach instead for reliability
    col_theme, _ = st.columns([1, 5])
    with col_theme:
        if st.button("🌙" if is_dark else "☀️", key="theme_toggle_btn",
                     help="Toggle theme"):
            new_theme = "light" if is_dark else "dark"
            st.session_state.sdm_theme = new_theme
            st.rerun()
