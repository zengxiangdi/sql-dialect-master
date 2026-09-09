#!/usr/bin/env python3
"""SQL Dialect Master - Local Streamlit Version

Optimized version with modular architecture.
Run: pip install sqlglot streamlit && streamlit run sdm_local.py
"""
import logging

import streamlit as st

# Set page config first
st.set_page_config(
    page_title="SQL Dialect Master", 
    page_icon="🔄",
    layout="wide", 
    initial_sidebar_state="expanded"
)

# Import shared context (single source of truth for app state/logic)
from frontend.app_context import load_data

# Import reusable components
from frontend.components import (
    render_history_card,
    render_main_header,
    render_sidebar_branding,
)

# Import modular tabs
from frontend.tabs.convert import render_convert_tab
from frontend.tabs.explain import render_explain_tab
from frontend.tabs.functions import render_functions_tab
from frontend.tabs.lineage import render_lineage_tab
from frontend.tabs.nl2sql import render_nl2sql_tab
from frontend.tabs.types import render_types_tab
from frontend.themes import (
    THEMES,
    export_theme_to_json,
    generate_keyboard_shortcuts_js,
    generate_theme_css,
    import_theme_from_json,
)

# Module logger
logger = logging.getLogger(__name__)

# Initialize session state
defaults = {
    "theme": "🌊 Ocean",
    "dark_mode": True,
    "history": [],
    "favorites": [],
    "load_sql": None,
    "last_conversion": None,
    "custom_theme": None,
    "show_welcome": True
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

    
# === THEME SETUP ===
# Determine active theme including custom override
if st.session_state.theme == "🛠️ Custom" and st.session_state.custom_theme:
    current_theme = st.session_state.custom_theme
else:
    # Fallback if custom selected but missing
    if st.session_state.theme == "🛠️ Custom":
        st.session_state.theme = "🌊 Ocean"
    current_theme = THEMES.get(st.session_state.theme, THEMES["🌊 Ocean"])

# Use centralized CSS and JS generation
theme_css = generate_theme_css(current_theme)
st.markdown(theme_css, unsafe_allow_html=True)

# Keyboard shortcuts
shortcuts_js = generate_keyboard_shortcuts_js()
st.markdown(shortcuts_js, unsafe_allow_html=True)

# Load data (cached)
types_data, funcs_data = load_data()


# === SIDEBAR ===
with st.sidebar:
    # Logo and branding (using component)
    st.markdown(render_sidebar_branding(current_theme), unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Theme selector logic
    available_themes = list(THEMES.keys())
    if st.session_state.custom_theme:
        available_themes.append("🛠️ Custom")
    
    try:
        current_index = available_themes.index(st.session_state.theme)
    except ValueError:
        current_index = 0
        
    selected_theme = st.selectbox(
        "🎨 Theme", 
        available_themes, 
        index=current_index,
        key="theme_selector"
    )
    
    if selected_theme != st.session_state.theme:
        st.session_state.theme = selected_theme
        st.rerun()
    
    # Theme Customization
    with st.expander("🛠️ Custom Theme"):
        tab_exp, tab_imp = st.tabs(["Export", "Import"])
        with tab_exp:
            st.caption("Current Theme JSON")
            st.code(export_theme_to_json(current_theme), language="json")
        with tab_imp:
            import_json = st.text_area("Paste JSON", height=100, label_visibility="collapsed", placeholder="Paste theme JSON here...")
            if st.button("Apply Theme", use_container_width=True):
                try:
                    new_theme = import_theme_from_json(import_json)
                    st.session_state.custom_theme = new_theme
                    st.session_state.theme = "🛠️ Custom"
                    st.toast("✅ Custom theme applied successfully!")
                    st.rerun()
                except ValueError as e:
                    st.error(f"Invalid theme: {e}")

    # Statistics
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.metric("Conversions", len(st.session_state.history), help="Total conversions in this session")
    with col_s2:
        st.metric("Favorites", len(st.session_state.favorites), help="Saved favorite queries")
    
    # History section
    st.markdown("---")
    st.markdown("#### 📜 Recent History")
    
    if st.session_state.history:
        for i, h in enumerate(st.session_state.history[-5:][::-1]):
            # Use render_history_card component
            st.markdown(render_history_card(h, current_theme), unsafe_allow_html=True)
            
            # Actions for history item
            cols = st.columns([1, 1, 1])
            with cols[0]:
                if st.button("Load", key=f"load_{i}"):
                    st.session_state.load_sql = h
                    st.rerun()
            with cols[1]:
                if st.button("Copy", key=f"copy_{i}"):
                    st.markdown(f'<textarea id="c_{i}" style="position:absolute;left:-9999px">{h["sql"]}</textarea><script>navigator.clipboard.writeText(document.getElementById("c_{i}").value)</script>', unsafe_allow_html=True)
                    st.toast("📋 Copied to clipboard!")
            with cols[2]:
                if h not in st.session_state.favorites:
                    if st.button("⭐", key=f"fav_{i}"):
                        st.session_state.favorites.append(h)
                        st.toast("⭐ Added to favorites!")
        
        if st.button("🗑️ Clear History", key="clear_hist", use_container_width=True):
            st.session_state.history = []
            st.rerun()
    else:
        st.info("No conversions yet. Start converting!")
    
    # Favorites section
    st.markdown("---")
    st.markdown("#### ⭐ Favorites")
    
    if st.session_state.favorites:
        for i, f in enumerate(st.session_state.favorites):
            with st.expander(f"{f['src'].upper()} → {f['tgt'].upper()}"):
                st.code(f["sql"], language="sql")
                if st.button("Load", key=f"load_fav_{i}"):
                    st.session_state.load_sql = f
                    st.rerun()
                if st.button("❌ Remove", key=f"rm_fav_{i}"):
                    st.session_state.favorites.pop(i)
                    st.rerun()
    else:
        st.info("Star your favorite queries!")
    
    # Keyboard shortcuts
    st.markdown("---")
    st.markdown("#### ⌨️ Shortcuts")
    st.caption("`Ctrl+Enter` Convert")
    st.caption("`Ctrl+Shift+F` Format")
    st.caption("`F11` Fullscreen")


# === MAIN CONTENT ===
# Header (using component)
st.markdown(render_main_header(current_theme), unsafe_allow_html=True)

st.markdown("")

# Main tabs with icons
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚡ Convert", 
    "📚 Functions", 
    "🗂️ Types", 
    "💬 NL2SQL", 
    "📊 Explain", 
    "🔗 Lineage"
])

# === TAB 1: SQL CONVERT ===
with tab1:
    render_convert_tab(current_theme)

# === TAB 2: FUNCTION ENCYCLOPEDIA ===
with tab2:
    render_functions_tab(funcs_data, current_theme)

# === TAB 3: TYPE MAPPING ===
with tab3:
    render_types_tab(types_data, current_theme)

# === TAB 4: NL2SQL ===
with tab4:
    render_nl2sql_tab()

# === TAB 5: EXPLAIN COMPARE ===
with tab5:
    render_explain_tab(current_theme)

# === TAB 6: SQL LINEAGE ===
with tab6:
    render_lineage_tab(current_theme)


# Footer
st.markdown("---")
st.markdown(f"""
<div style="text-align: center; padding: 1rem; opacity: 0.7;">
    <p>SQL Dialect Master v1.0.1 · Built with ❤️ using Streamlit & sqlglot</p>
    <p style="font-size: 0.8rem;">Supports 12 databases · 298 functions · 36 data types · 40 conversion rules</p>
</div>
""", unsafe_allow_html=True)
