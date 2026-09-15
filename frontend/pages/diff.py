"""Semantic Diff Workspace for SQL Dialect Master v2.

Full workspace with:
- Overall semantic classification banner
- Finding list (clickable, with severity indicators)
- Inspector panel (shows selected finding details)
- Semantic vs Text diff tab switcher
- Integration with Convert workspace via ?page=diff&find=N
"""
from __future__ import annotations

import streamlit as st

from backend.core.semantic_diff import diff_sql_ast
from frontend.core.design_tokens import ColorTokens
from frontend.core.viewmodels import (
    SemanticDiffViewModel,
)

# ── Page definition ────────────────────────────────────────────────────

def render_diff_page(theme: ColorTokens) -> None:
    """Render the Semantic Diff workspace."""

    _render_header(theme)
    _render_input_section(theme)

    # Check for auto-populate from Convert → Diff navigation
    pending = st.session_state.get("sdm_pending_diff")
    if pending and not st.session_state.get("diff_last_vm"):
        st.session_state.diff_src_sql = pending.get("source", "")
        st.session_state.diff_tgt_sql = pending.get("target", "")
        st.session_state.diff_src_dialect = pending.get("src_dialect", "postgres")
        st.session_state.diff_tgt_dialect = pending.get("tgt_dialect", "mysql")
        st.session_state.sdm_pending_diff = None  # consume

    # Get saved inputs
    src_sql = st.session_state.get("diff_src_sql", "")
    tgt_sql = st.session_state.get("diff_tgt_sql", "")

    # Render results if available
    vm: SemanticDiffViewModel | None = st.session_state.get("diff_last_vm")
    if vm is not None:
        selected_idx = st.session_state.get("sdm_selected_finding")
        _render_results(vm, src_sql, tgt_sql, selected_idx, theme)


def _render_header(theme: ColorTokens) -> None:
    """Render the page header."""
    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                Semantic Diff
            </div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                AST-based semantic equivalence analysis between two SQL statements
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_input_section(theme: ColorTokens) -> None:
    """Render the SQL input section."""
    col_src, col_tgt = st.columns(2)

    with col_src:
        st.markdown(
            '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            'text-transform:uppercase; color:' + theme.text_muted + '; margin-bottom:6px;">'
            'Source SQL</div>',
            unsafe_allow_html=True,
        )
        st.text_area(
            "Source",
            key="diff_src_sql",
            height=160,
            label_visibility="collapsed",
            placeholder="SELECT DATE_ADD(created_at, INTERVAL 7 DAY) FROM users",
        )
        st.selectbox(
            "Dialect",
            ["postgres", "mysql", "hive", "spark", "oracle", "tsql"],
            key="diff_src_dialect",
            label_visibility="collapsed",
        )

    with col_tgt:
        st.markdown(
            '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            'text-transform:uppercase; color:' + theme.text_muted + '; margin-bottom:6px;">'
            'Target SQL</div>',
            unsafe_allow_html=True,
        )
        st.text_area(
            "Target",
            key="diff_tgt_sql",
            height=160,
            label_visibility="collapsed",
            placeholder="SELECT created_at + INTERVAL '7 days' FROM users",
        )
        st.selectbox(
            "Dialect",
            ["postgres", "mysql", "hive", "spark", "oracle", "tsql"],
            key="diff_tgt_dialect",
            label_visibility="collapsed",
        )

    # Compare button
    col_btn, _ = st.columns([1, 5])
    with col_btn:
        if st.button("Compare", type="primary", key="diff_compare", use_container_width=True):
            _run_comparison(theme)


def _run_comparison(theme: ColorTokens) -> None:
    """Run semantic diff and store result in session state."""
    src_sql = st.session_state.get("diff_src_sql", "")
    tgt_sql = st.session_state.get("diff_tgt_sql", "")
    src_dialect = st.session_state.get("diff_src_dialect", "postgres")
    tgt_dialect = st.session_state.get("diff_tgt_dialect", "mysql")

    if not src_sql.strip() or not tgt_sql.strip():
        st.warning("Please enter both SQL statements.")
        return

    with st.spinner("Analyzing semantic equivalence..."):
        backend_result = diff_sql_ast(src_sql, tgt_sql, src_dialect, tgt_dialect)

    vm = SemanticDiffViewModel.from_backend(
        source_sql=src_sql,
        target_sql=tgt_sql,
        source_dialect=src_dialect,
        target_dialect=tgt_dialect,
        diff=backend_result,
    )
    st.session_state.diff_last_vm = vm
    st.session_state.sdm_selected_finding = None
    st.rerun()


def _render_results(
    vm: SemanticDiffViewModel,
    source_sql: str,
    target_sql: str,
    selected_idx: int | None,
    theme: ColorTokens,
) -> None:
    """Render the diff results with finding list and inspector."""
    from frontend.ui.diff import render_semantic_diff_workspace
    render_semantic_diff_workspace(vm, source_sql, target_sql, theme, selected_idx)
