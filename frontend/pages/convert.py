"""Convert Workspace for SQL Dialect Master v2.

This is the primary workspace — a professional SQL IDE-style interface
for dialect conversion with semantic analysis integration.

Fixes the batch conversion bug from v1: properly delegates statement
splitting to the canonical backend API.
"""
from __future__ import annotations

import streamlit as st

from frontend.app_context_v2 import (
    DIALECTS,
    batch_convert_sql,
    convert_sql,
    format_sql_local,
    split_sql_statements,
)
from frontend.core.design_tokens import (
    ColorTokens,
)
from frontend.core.escaping import esc
from frontend.core.navigation import create_navigation_intent
from frontend.core.viewmodels import (
    BatchConversionViewModel,
    ConversionViewModel,
)
from frontend.ui.status import render_batch_result, render_result_panel


def render_convert_page(theme: ColorTokens) -> None:
    """Render the Convert workspace page."""

    # ── Toolbar ──────────────────────────────────────────────────────
    _render_toolbar(theme)

    # ── Dialect selectors + SQL editors ────────────────────────────
    src_dialect = st.selectbox(
        "Source dialect",
        DIALECTS,
        index=DIALECTS.index("postgres") if "postgres" in DIALECTS else 0,
        key="convert_src",
        label_visibility="collapsed",
    )
    tgt_dialect = st.selectbox(
        "Target dialect",
        DIALECTS,
        index=DIALECTS.index("mysql") if "mysql" in DIALECTS else 0,
        key="convert_tgt",
        label_visibility="collapsed",
    )

    # Swap button between selectors
    col_swap, _ = st.columns([1, 10])
    with col_swap:
        if st.button("⇄", key="swap_dialects", help="Swap source and target dialects"):
            st.session_state.convert_src, st.session_state.convert_tgt = st.session_state.convert_tgt, st.session_state.convert_src
            st.rerun()

    # ── SQL editors (two-panel) ────────────────────────────────────
    col_src, col_tgt = st.columns([1, 1])

    with col_src:
        st.markdown(
            f'<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            f'text-transform:uppercase; color:{theme.text_muted}; margin-bottom:6px;">'
            f'Source · {esc(src_dialect.upper())}</div>',
            unsafe_allow_html=True,
        )
        src_sql = st.text_area(
            "Source SQL",
            key="convert_src_sql",
            height=300,
            placeholder="SELECT * FROM users WHERE created_at > NOW() - INTERVAL '7 days'",
            label_visibility="collapsed",
        )

        col_fmt, col_clear = st.columns([1, 1])
        with col_fmt:
            if st.button("Format", key="format_src", use_container_width=True, type="secondary"):
                formatted = format_sql_local(src_sql, src_dialect)
                st.session_state.convert_src_sql = formatted
                st.rerun()
        with col_clear:
            if st.button("Clear", key="clear_src", use_container_width=True):
                st.session_state.convert_src_sql = ""
                st.rerun()

    with col_tgt:
        st.markdown(
            f'<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            f'text-transform:uppercase; color:{theme.text_muted}; margin-bottom:6px;">'
            f'Target · {esc(tgt_dialect.upper())}</div>',
            unsafe_allow_html=True,
        )

        # Show converted SQL or placeholder
        target_sql_display = st.session_state.get("convert_target_sql", "")
        if target_sql_display:
            st.code(target_sql_display, language="sql")
            col_copy, col_dl = st.columns([1, 1])
            with col_copy:
                st.copy_button("Copy", key="copy_tgt", data=target_sql_display)
            with col_dl:
                st.download_button("Download", target_sql_display, "converted.sql", mime="text/sql")
        else:
            st.markdown(
                f'<div style="border:1px dashed {theme.border}; border-radius:6px; '
                f'padding:40px; text-align:center; color:{theme.text_muted};">'
                f'Converted SQL will appear here</div>',
                unsafe_allow_html=True,
            )

    # ── Convert button ─────────────────────────────────────────────
    convert_clicked = st.button("Convert", key="convert_btn", type="primary", use_container_width=True)

    if convert_clicked and src_sql.strip():
        with st.spinner("Converting..."):
            result = convert_sql(src_sql, src_dialect, tgt_dialect)

        vm = ConversionViewModel.from_transpile_result(result)
        st.session_state.convert_last_vm = vm
        st.session_state.convert_target_sql = vm.target_sql or ""

        # Add to history
        _add_to_history(vm, theme)
        st.rerun()
    elif convert_clicked and not src_sql.strip():
        st.warning("Please enter SQL to convert.")

    # ── Result display ─────────────────────────────────────────────
    vm: ConversionViewModel | None = st.session_state.get("convert_last_vm")
    if vm is not None:
        st.markdown("---")
        render_result_panel(
            sql=vm.target_sql or "",
            source_dialect=vm.source_dialect,
            target_dialect=vm.target_dialect,
            warnings=vm.warnings,
            transformations=vm.transformations,
            compatibility_notes=vm.compatibility_notes,
            error_message=vm.error_message,
            semantic_label=vm.semantic_label,
            semantic_status=vm.semantic_status,
            theme=theme,
        )

        # Navigate to Diff workspace
        if vm.target_sql and vm.success:
            col_diff, _ = st.columns([1, 3])
            with col_diff:
                if st.button("Semantic Diff →", key="run_semantic_diff", type="secondary", use_container_width=True):
                    intent = create_navigation_intent(
                        target_page="diff",
                        action="open_diff",
                        source=vm.source_sql,
                        target=vm.target_sql,
                        src_dialect=vm.source_dialect,
                        tgt_dialect=vm.target_dialect,
                    )
                    st.session_state.sdm_navigation_intent = intent
                    st.rerun()

    # ── Batch conversion ───────────────────────────────────────────
    with st.expander("Batch Conversion", expanded=False):
        _render_batch_section(src_dialect, tgt_dialect, theme)


def _render_toolbar(theme: ColorTokens) -> None:
    """Render the top toolbar for the Convert page."""
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; justify-content:space-between;
                    padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div>
                <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                    Convert
                </div>
                <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                    Transform SQL between database dialects
                </div>
            </div>
            <div style="display:flex; gap:8px;">
                <span style="font-size:11px; color:{theme.text_muted}; font-family:monospace;">
                    Click Convert to run
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_batch_section(src_dialect: str, tgt_dialect: str, theme: ColorTokens) -> None:
    """Render the batch conversion section."""
    st.markdown(
        '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        'text-transform:uppercase; color:' + theme.text_muted + '; margin-bottom:8px;">'
        'Batch Mode</div>',
        unsafe_allow_html=True,
    )

    batch_sql = st.text_area(
        "Enter SQL statements (one per line or separated by semicolons)",
        key="batch_sql_input",
        height=150,
        placeholder="SELECT * FROM users;\nSELECT id, name FROM orders WHERE status = 'active';",
    )

    col_bs, col_bt, col_bb = st.columns([1, 1, 2])
    with col_bs:
        batch_src = st.selectbox("Source", DIALECTS, index=DIALECTS.index("postgres") if "postgres" in DIALECTS else 0,
                                   key="batch_src", label_visibility="collapsed")
    with col_bt:
        batch_tgt = st.selectbox("Target", DIALECTS, index=DIALECTS.index("mysql") if "mysql" in DIALECTS else 0,
                                   key="batch_tgt", label_visibility="collapsed")
    with col_bb:
        if st.button("Convert All", key="batch_convert_btn", type="primary", use_container_width=True):
            if not batch_sql.strip():
                st.warning("Please enter SQL statements.")
            else:
                with st.spinner("Batch converting..."):
                    # Use canonical backend for proper semicolon splitting
                    statements = split_sql_statements(batch_sql, batch_src)
                    results = batch_convert_sql(statements, batch_src, batch_tgt)
                    bvm = BatchConversionViewModel.from_results(statements, results)
                    st.session_state.batch_last_vm = bvm
                st.rerun()

    bvm: BatchConversionViewModel | None = st.session_state.get("batch_last_vm")
    if bvm is not None:
        render_batch_result(
            total=bvm.total,
            succeeded=bvm.succeeded,
            failed=bvm.failed,
            items=bvm.items,
            theme=theme,
        )

        # Download all
        combined = "\n\n".join(
            item.converted_sql or f"-- Statement {item.statement_index} failed"
            for item in bvm.items
        )
        st.download_button(
            "Download All",
            combined,
            "batch_converted.sql",
            mime="text/sql",
            use_container_width=True,
        )


def _add_to_history(vm: ConversionViewModel, theme: ColorTokens) -> None:
    """Add a successful conversion to session history."""
    if not vm.success:
        return
    from datetime import UTC, datetime
    import uuid
    entry = {
        "identity": uuid.uuid4().hex[:8],
        "sql": vm.source_sql,
        "src": vm.source_dialect,
        "tgt": vm.target_dialect,
        "result": vm.target_sql,
        "status": vm.status,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if "sdm_history" not in st.session_state:
        st.session_state.sdm_history = []
    st.session_state.sdm_history.append(entry)
    if "sdm_favorites" not in st.session_state:
        st.session_state.sdm_favorites = []
