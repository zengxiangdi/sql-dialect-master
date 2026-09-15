"""SQL Dialect Master v2 — Professional Developer Workspace.

Refactored frontend architecture with:
- Dark / Light theme system
- Sidebar navigation (Workspace / Library / System)
- ViewModel-based state management
- Unified NavigationIntent for cross-page handoffs
- Command Palette (⌘K / Ctrl+K)
- Security-safe HTML rendering
- Fixed batch conversion bug
"""
import logging

import streamlit as st

# ── Page config (must be first Streamlit call) ──────────────────────
st.set_page_config(
    page_title="SQL Dialect Master",
    page_icon="⟷",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Import new architecture ──────────────────────────────────────────
from frontend.app_context_v2 import load_data_v2
from frontend.core.design_tokens import THEMES
from frontend.core.navigation import (
    NavigationIntent,
    consume_navigation_intent,
)
from frontend.core.styles import generate_css
from frontend.pages.convert import render_convert_page
from frontend.pages.diff import render_diff_page
from frontend.pages.functions import render_functions_page
from frontend.pages.history import render_history_page
from frontend.pages.lineage import render_lineage_page
from frontend.pages.nl2sql import render_nl2sql_page
from frontend.pages.query_analysis import render_query_analysis_page
from frontend.pages.runtime import render_runtime_page
from frontend.pages.settings import render_settings_page
from frontend.pages.templates import render_templates_page
from frontend.pages.types import render_types_page
from frontend.ui.command_palette import render_command_palette

# ── Page registry (must be before navigation processing) ─────────────
PAGE_MAP = {
    "convert": ("Convert", render_convert_page),
    "nl2sql": ("NL2SQL", render_nl2sql_page),
    "diff": ("Semantic Diff", render_diff_page),
    "lineage": ("Lineage", render_lineage_page),
    "runtime": ("Runtime", render_runtime_page),
    "functions": ("Functions", render_functions_page),
    "types": ("Types", render_types_page),
    "templates": ("Templates", render_templates_page),
    "history": ("History", render_history_page),
    "settings": ("Settings", render_settings_page),
    "query_analysis": ("Query Analysis", render_query_analysis_page),
}


# ── Initialize session state ─────────────────────────────────────────
_NAV_KEY = "sdm_navigation_intent"
_FINDING_KEY = "sdm_selected_finding_index"

_DEFAULTS = {
    "sdm_theme": "dark",
    "sdm_history": [],
    "sdm_favorites": [],
    "convert_last_vm": None,
    "batch_last_vm": None,
    "nl_last_vm": None,
    "lineage_last_vm": None,
    "qa_last_result": None,
    "diff_last_vm": None,
    _NAV_KEY: NavigationIntent(),
    _FINDING_KEY: None,
}
for key, default in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ── Process navigation intent (consumed once per request) ────────────
_pending = consume_navigation_intent()
if _pending and _pending.is_valid and _pending.target_page in PAGE_MAP:
    st.query_params["page"] = _pending.target_page
    if _pending.action == "open_diff" and _pending.get_payload("source"):
        st.session_state.diff_src_sql = _pending.get_payload("source")
        st.session_state.diff_tgt_sql = _pending.get_payload("target")
        st.session_state.diff_src_dialect = _pending.get_payload("src_dialect", "postgres")
        st.session_state.diff_tgt_dialect = _pending.get_payload("tgt_dialect", "mysql")
        st.session_state.diff_last_vm = None
        st.session_state[_FINDING_KEY] = None
    elif _pending.action == "open_conversion" and _pending.get_payload("sql"):
        st.session_state.convert_src_sql = _pending.get_payload("sql")
        st.session_state.convert_src = _pending.get_payload("dialect", "postgres")
        st.session_state.convert_target_sql = ""
        st.session_state.convert_last_vm = None
    elif _pending.action == "select_finding" and _pending.has_payload("finding_index"):
        st.session_state[_FINDING_KEY] = _pending.get_payload("finding_index")
    st.rerun()


# ── Theme setup ──────────────────────────────────────────────────────
theme_name: str = st.session_state.get("sdm_theme", "dark")
if theme_name not in THEMES:
    theme_name = "dark"
    st.session_state.sdm_theme = "dark"
current_theme = THEMES[theme_name]

# Apply CSS
st.markdown(generate_css(current_theme), unsafe_allow_html=True)

# ── Load static data ─────────────────────────────────────────────────
types_data, funcs_data = load_data_v2()

# ── Determine active page ────────────────────────────────────────────
requested_page = st.query_params.get("page", "convert")
if requested_page not in PAGE_MAP:
    requested_page = "convert"
page_label, page_renderer = PAGE_MAP[requested_page]

# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    # Branding
    st.markdown(
        f"""
        <div style="padding:12px 16px; border-bottom:1px solid {current_theme.border};">
            <div style="font-size:12px; font-weight:700; letter-spacing:0.1em;
                        text-transform:uppercase; color:{current_theme.text_muted};">
                SQL Dialect Master
            </div>
            <div style="font-size:10px; color:{current_theme.text_muted}; margin-top:2px;
                        font-family:monospace;">
                v2.0 · Developer Workspace
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Navigation groups
    NAV_GROUPS = [
        ("WORKSPACE", [
            ("convert", "⟷", "Convert"),
            ("nl2sql", "💬", "NL2SQL"),
            ("diff", "◈", "Diff"),
            ("lineage", "⌇", "Lineage"),
            ("runtime", "▶", "Runtime"),
        ]),
        ("LIBRARY", [
            ("functions", "ƒ", "Functions"),
            ("types", "T", "Types"),
            ("templates", "▤", "Templates"),
            ("history", "◷", "History"),
        ]),
        ("SYSTEM", [
            ("settings", "⚙", "Settings"),
            ("query_analysis", "◉", "Query Analysis"),
        ]),
    ]

    for group_label, items in NAV_GROUPS:
        st.markdown(
            f'<div style="font-size:10px; font-weight:600; letter-spacing:0.08em; '
            f'text-transform:uppercase; color:{current_theme.text_muted}; '
            f'padding:8px 16px 4px;">{group_label}</div>',
            unsafe_allow_html=True,
        )
        for page_id, icon, label in items:
            active = "active" if page_id == requested_page else ""
            bg = current_theme.selected_bg if active else "transparent"
            color = current_theme.accent if active else current_theme.text_secondary

            if st.button(
                f"  {icon}  {label}",
                key=f"nav_{page_id}",
                use_container_width=True,
                help=label,
            ):
                st.query_params["page"] = page_id
                st.rerun()

    # Theme toggle
    st.markdown("---")
    col_theme_btn, _ = st.columns([1, 4])
    with col_theme_btn:
        if st.button("🌙" if theme_name == "dark" else "☀️", key="theme_toggle"):
            new_theme = "light" if theme_name == "dark" else "dark"
            st.session_state.sdm_theme = new_theme
            st.rerun()

    # History count
    history = st.session_state.get("sdm_history", [])
    st.caption(f"{len(history)} conversions")


# ── Main workspace ───────────────────────────────────────────────────
st.markdown(f"<div class='sdm-content'>{page_label}</div>", unsafe_allow_html=True)

# Pass theme to page renderer
page_renderer(current_theme)

# ── Command Palette ──────────────────────────────────────────────────
render_command_palette(current_theme)

# ── Footer ───────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    f"""
    <div style="text-align:center; padding:8px; opacity:0.6; font-size:11px; color:{current_theme.text_muted};">
        SQL Dialect Master v2.0 · Professional SQL Developer Workspace
    </div>
    """,
    unsafe_allow_html=True,
)
