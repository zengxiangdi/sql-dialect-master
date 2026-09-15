"""NL2SQL Workspace for SQL Dialect Master v2."""
from __future__ import annotations

import streamlit as st

from frontend.app_context_v2 import DIALECTS, generate_nl2sql, get_dialect_label
from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc
from frontend.core.viewmodels import NL2SQLViewModel


def render_nl2sql_page(theme: ColorTokens) -> None:
    """Render the NL2SQL workspace."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">NL2SQL</div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Generate SQL from natural language descriptions
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_nl, col_dialect = st.columns([3, 1])
    with col_nl:
        nl_input = st.text_area(
            "Describe your query",
            key="nl_input",
            height=100,
            placeholder="e.g., Get all users who placed orders in the last 7 days with total amount > $100",
        )
    with col_dialect:
        nl_dialect = st.selectbox(
            "Target dialect",
            DIALECTS,
            index=DIALECTS.index("postgres") if "postgres" in DIALECTS else 0,
            format_func=get_dialect_label,
            key="nl_dialect",
        )

    col_table, col_gen = st.columns([2, 1])
    with col_table:
        table_hint = st.text_input(
            "Table hint (optional)",
            key="nl_table_hint",
            placeholder="e.g., users, orders",
            label_visibility="collapsed",
        )
    with col_gen:
        st.markdown("")
        generate_clicked = st.button("Generate SQL", type="primary", key="nl_generate", use_container_width=True)

    if generate_clicked and nl_input.strip():
        with st.spinner("Generating..."):
            result = generate_nl2sql(nl_input, nl_dialect, table_hint or None)

        vm = NL2SQLViewModel.from_nl2sql_result(result)
        st.session_state.nl_last_vm = vm
        st.rerun()

    vm: NL2SQLViewModel | None = st.session_state.get("nl_last_vm")
    if vm is None:
        return

    if not vm.success:
        st.error(f"Generation failed: {esc(vm.explanation) or 'No SQL produced'}")
        return

    # Result display
    st.markdown(
        '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        'text-transform:uppercase; color:#' + theme.text_muted[1:] + '; margin:16px 0 8px;">'
        'Generated SQL</div>',
        unsafe_allow_html=True,
    )
    st.code(vm.sql or "", language="sql")

    # Action buttons
    col_copy, col_convert, col_diff = st.columns(3)
    with col_copy:
        st.copy_button("Copy", data=vm.sql or "")
    with col_convert:
        if st.button("Convert", key="nl_to_convert"):
            st.session_state.convert_src_sql = vm.sql or ""
            st.query_params["page"] = "convert"
            st.rerun()
    with col_diff:
        if st.button("Semantic Diff", key="nl_to_diff"):
            st.session_state.sdm_pending_diff = {"source": vm.sql or "", "src_dialect": vm.dialect,
                                                  "target": vm.sql or "", "tgt_dialect": vm.dialect}
            st.query_params["page"] = "diff"
            st.rerun()

    # Confidence
    st.markdown(
        f'<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        f'text-transform:uppercase; color:{theme.text_muted}; margin:16px 0 8px;">'
        f'Confidence</div>',
        unsafe_allow_html=True,
    )
    conf_color = theme.success if vm.confidence >= 0.7 else theme.warning if vm.confidence >= 0.5 else theme.danger
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:8px;">'
        f'<span style="color:{conf_color}; font-size:20px; font-weight:700;">{vm.confidence:.0%}</span>'
        f'<span style="color:{theme.text_secondary}; font-size:12px;">overall</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if vm.explanation:
        st.info(esc(vm.explanation))

    if vm.parsed_elements:
        with st.expander("Parsed Elements"):
            pe = vm.parsed_elements
            for key, values in pe.items():
                if values:
                    st.markdown(f"**{esc(str(key))}**")
                    for v in values[:5]:
                        st.code(esc(str(v)))
