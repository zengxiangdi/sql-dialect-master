"""Settings page for SQL Dialect Master v2."""
from __future__ import annotations

import streamlit as st

from frontend.core.design_tokens import ColorTokens


def render_settings_page(theme: ColorTokens) -> None:
    """Render the Settings page."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                Settings
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Theme
    st.markdown("##### Theme")
    col_theme_sel, _ = st.columns([2, 1])
    with col_theme_sel:
        current = st.session_state.get("sdm_theme", "dark")
        selected = st.selectbox("Color theme", ["dark", "light"], index=["dark", "light"].index(current) if current in ["dark", "light"] else 0, key="settings_theme_sel")
    with st.container():
        if st.button("Apply Theme", key="settings_apply_theme"):
            st.session_state.sdm_theme = selected
            st.rerun()

    # Keyboard shortcuts reference
    st.markdown("---")
    st.markdown("##### Notes")
    st.markdown("""
    Streamlit does not support native keyboard shortcuts.
    Actions are performed via buttons and menu selections.
    """)

    # About
    st.markdown("---")
    st.markdown("##### About")
    st.markdown("""
    **SQL Dialect Master v2.0**

    Professional SQL conversion workspace powered by sqlglot and semantic analysis.

    - 12 supported dialects
    - 298+ functions indexed
    - 36+ type mappings
    - Semantic diff analysis
    """)
