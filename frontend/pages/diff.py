"""Semantic Diff Workspace for SQL Dialect Master v2."""
from __future__ import annotations

import streamlit as st

from backend.core.semantic_diff import diff_sql_ast
from frontend.core.design_tokens import (
    ColorTokens,
)
from frontend.ui.diff import render_semantic_diff_view


def render_diff_page(theme: ColorTokens) -> None:
    """Render the Semantic Diff workspace."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">Semantic Diff</div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Compare two SQL statements for semantic equivalence
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_src, col_tgt = st.columns(2)

    with col_src:
        st.markdown(
            '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            'text-transform:uppercase; color:' + theme.text_muted + '; margin-bottom:6px;">Source SQL</div>',
            unsafe_allow_html=True,
        )
        src_sql = st.text_area("Source", key="diff_src_sql", height=200, label_visibility="collapsed")
        src_dialect = st.selectbox("Dialect", ["postgres", "mysql", "hive", "spark"], key="diff_src_dialect")

    with col_tgt:
        st.markdown(
            '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            'text-transform:uppercase; color:' + theme.text_muted + '; margin-bottom:6px;">Target SQL</div>',
            unsafe_allow_html=True,
        )
        tgt_sql = st.text_area("Target", key="diff_tgt_sql", height=200, label_visibility="collapsed")
        tgt_dialect = st.selectbox("Dialect", ["postgres", "mysql", "hive", "spark"], key="diff_tgt_dialect")

    if st.button("Compare", type="primary", key="diff_compare", use_container_width=True):
        if not src_sql.strip() or not tgt_sql.strip():
            st.warning("Please enter both SQL statements.")
        else:
            with st.spinner("Analyzing..."):
                result = diff_sql_ast(src_sql, tgt_sql, src_dialect, tgt_dialect)
            st.session_state.diff_last_result = result
            st.rerun()

    result = st.session_state.get("diff_last_result")
    if result is None:
        return

    render_semantic_diff_view(
        source_sql=result.source_normalized or src_sql,
        target_sql=result.target_normalized or tgt_sql,
        source_dialect=src_dialect,
        target_dialect=tgt_dialect,
        semantic_classification=result.semantic_classification,
        structured_differences=result.structured_differences,
        differences=result.differences,
        confidence=result.confidence,
        theme=theme,
    )
