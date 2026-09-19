"""NL2SQL Workspace for SQL Dialect Master v2.

Professional workspace for natural-language-to-SQL generation.
Shows result with confidence, explanation, parsed elements, and
conversion/diff handoff buttons.
"""
from __future__ import annotations

import streamlit as st

from frontend.app_context_v2 import DIALECTS, generate_nl2sql, get_dialect_label
from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc
from frontend.core.state import SessionState
from frontend.core.viewmodels import NL2SQLViewModel

# ── Example queries (no emoji) ─────────────────────────────────────────

EXAMPLE_QUERIES: dict[str, str] = {
    "Count all users": "统计所有用户的数量",
    "Date filter": "查询最近7天的订单",
    "Conditional": "查询金额大于100的订单",
    "Group by": "按部门分组统计员工数量",
    "Order and limit": "查询前10个用户按得分降序排列",
    "Join query": "查询用户和订单关联的数据",
    "Average": "查询员工的平均薪资",
    "Like search": "查询名字包含张的用户",
    "This month": "查询本月所有订单的总金额",
    "Top N": "查询销售额最高的前5个产品",
}


def render_nl2sql_page(theme: ColorTokens) -> None:
    """Render the NL2SQL workspace."""
    state = SessionState.get()

    _render_header(theme)
    _render_input_section(theme)
    _render_result_section(state, theme)


def _render_header(theme: ColorTokens) -> None:
    """Render the page header."""
    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                NL2SQL
            </div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Generate SQL from natural language descriptions
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_input_section(theme: ColorTokens) -> None:
    """Render the input section: NL text, dialect, table hint."""
    col_nl, col_dialect = st.columns([3, 1])

    with col_nl:
        # Example selector
        examples = list(EXAMPLE_QUERIES.keys())
        selected_example = st.selectbox(
            "Quick example",
            [""] + examples,
            key="nl_example_sel",
            label_visibility="collapsed",
        )
        if selected_example:
            st.session_state.nl_input_text = EXAMPLE_QUERIES[selected_example]

        st.text_area(
            "Describe your query",
            key="nl_input_text",
            height=100,
            label_visibility="collapsed",
            placeholder="e.g., Get users who placed orders in the last 7 days",
        )

    with col_dialect:
        st.markdown(
            '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            'text-transform:uppercase; color:' + theme.text_muted + '; margin-bottom:6px;">'
            'Target dialect</div>',
            unsafe_allow_html=True,
        )
        st.selectbox(
            "Dialect",
            DIALECTS,
            index=DIALECTS.index("postgres") if "postgres" in DIALECTS else 0,
            format_func=get_dialect_label,
            key="nl_dialect",
        )

    # Table hint + generate
    col_hint, col_gen = st.columns([3, 1])
    with col_hint:
        st.text_input(
            "Table hint (optional)",
            key="nl_table_hint",
            label_visibility="collapsed",
            placeholder="e.g., users, orders, products",
        )
    with col_gen:
        st.markdown("")
        if st.button("Generate SQL", type="primary", key="nl_generate", use_container_width=True):
            _run_generation(theme)


def _run_generation(theme: ColorTokens) -> None:
    """Run NL2SQL generation and store result."""
    nl_input = st.session_state.get("nl_input_text", "")
    dialect = st.session_state.get("nl_dialect", "postgres")
    table_hint = st.session_state.get("nl_table_hint", "")

    if not nl_input.strip():
        st.warning("Please describe your query.")
        return

    with st.spinner("Generating SQL..."):
        result = generate_nl2sql(nl_input, dialect, table_hint or None)

    vm = NL2SQLViewModel.from_nl2sql_result(result)
    state.nl_last_vm = vm
    state.nl_generation_error = None
    st.rerun()


def _render_result_section(state: SessionState, theme: ColorTokens) -> None:
    """Render the generation result."""
    vm: NL2SQLViewModel | None = state.nl_last_vm
    error: str | None = state.nl_generation_error

    if error:
        st.error(f"Generation failed: {esc(error)}")
        return

    if vm is None:
        return

    if not vm.success:
        st.error(f"Generation failed: {esc(vm.explanation or 'No SQL produced')}")
        return

    _render_generated_sql(vm, theme)
    _render_confidence(vm, theme)
    _render_explanation(vm, theme)
    _render_parsed_elements(vm, theme)
    _render_action_buttons(vm, theme)


def _render_generated_sql(vm: NL2SQLViewModel, theme: ColorTokens) -> None:
    """Render the generated SQL code block."""
    sql = vm.clean_sql()
    if not sql:
        return

    st.markdown(
        '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        'text-transform:uppercase; color:' + theme.text_muted + '; margin:16px 0 8px;">'
        'Generated SQL</div>',
        unsafe_allow_html=True,
    )
    st.code(sql, language="sql")


def _render_confidence(vm: NL2SQLViewModel, theme: ColorTokens) -> None:
    """Render the overall confidence indicator."""
    level_colors = {
        "high": theme.success,
        "review": theme.warning,
        "low": theme.danger,
    }
    color = level_colors.get(vm.confidence_level, theme.text_muted)

    st.markdown(
        '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        'text-transform:uppercase; color:' + theme.text_muted + '; margin:12px 0 8px;">'
        'Confidence</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:12px; padding:8px 12px;
                    background:{color}12; border:1px solid {color}30; border-radius:6px;">
            <span style="font-size:20px; font-weight:700; color:{color}; font-family:monospace;">
                {vm.confidence:.0%}
            </span>
            <span style="font-size:12px; color:{color}; font-weight:500;">
                {esc(vm.confidence_label)}
            </span>
            <span style="font-size:11px; color:{theme.text_muted}; margin-left:auto;">
                Overall
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_explanation(vm: NL2SQLViewModel, theme: ColorTokens) -> None:
    """Render the generation explanation."""
    if not vm.explanation:
        return

    st.markdown(
        '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        'text-transform:uppercase; color:' + theme.text_muted + '; margin:12px 0 8px;">'
        'Explanation</div>',
        unsafe_allow_html=True,
    )
    st.info(esc(vm.explanation))


def _render_parsed_elements(vm: NL2SQLViewModel, theme: ColorTokens) -> None:
    """Render parsed elements: tables, columns, values."""
    has_elements = vm.tables or vm.columns or vm.values or vm.token_count > 0

    if not has_elements:
        return

    st.markdown(
        '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        'text-transform:uppercase; color:' + theme.text_muted + '; margin:12px 0 8px;">'
        'Parsed Elements</div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(4)
    with cols[0]:
        if vm.tables:
            st.markdown("**Tables**")
            for t in vm.tables[:5]:
                st.caption(f"`{esc(t)}`")
        else:
            st.caption("—")

    with cols[1]:
        if vm.columns:
            st.markdown("**Columns**")
            for c in vm.columns[:5]:
                st.caption(f"`{esc(c)}`")
        else:
            st.caption("—")

    with cols[2]:
        if vm.values:
            st.markdown("**Values**")
            for v in vm.values[:5]:
                st.caption(f"`{esc(v)}`")
        else:
            st.caption("—")

    with cols[3]:
        st.markdown("**Metadata**")
        if vm.is_chinese:
            st.caption("Language: Chinese")
        st.caption(f"Tokens: {vm.token_count}")


def _render_action_buttons(vm: NL2SQLViewModel, theme: ColorTokens) -> None:
    """Render action buttons: Copy, Download, Open in Converter, Semantic Diff."""
    sql = vm.clean_sql()
    if not sql:
        return

    col_copy, col_dl, col_convert, col_diff = st.columns(4)

    with col_copy:
        st.copy_button("Copy", data=sql)

    with col_dl:
        st.download_button("Download", sql, "generated.sql", mime="text/sql")

    with col_convert:
        if st.button("Open in Converter", key="nl_to_convert", use_container_width=True):
            from frontend.core.navigation import create_navigation_intent
            intent = create_navigation_intent(
                target_page="convert",
                action="open_conversion",
                sql=sql,
                dialect=vm.dialect,
                origin="nl2sql",
            )
            st.session_state.sdm_navigation_intent = intent
            st.rerun()

    with col_diff:
        if st.button("Semantic Diff", key="nl_to_diff", use_container_width=True):
            from frontend.core.navigation import create_navigation_intent
            intent = create_navigation_intent(
                target_page="diff",
                action="open_diff",
                source=sql,
                target=sql,
                src_dialect=vm.dialect,
                tgt_dialect=vm.dialect,
            )
            st.session_state.sdm_navigation_intent = intent
            st.rerun()
