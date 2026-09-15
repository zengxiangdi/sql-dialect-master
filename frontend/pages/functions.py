"""Function Library page for SQL Dialect Master v2."""
from __future__ import annotations

import streamlit as st

from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc

CATEGORY_ICONS = {
    "string": "S",
    "date": "D",
    "math": "M",
    "aggregate": "A",
    "window": "W",
    "conditional": "C",
    "conversion": "V",
    "json": "J",
    "array": "L",
    "system": "Y",
    "geo": "G",
}


def render_functions_page(funcs_data: dict, theme: ColorTokens) -> None:
    """Render the Function Library page."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                Function Library
            </div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Search and compare SQL functions across dialects
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    all_funcs = funcs_data.get("functions", [])

    # Search and filter
    col_search, col_cat = st.columns([2, 1])
    with col_search:
        query = st.text_input("Search", key="func_search", placeholder="Type function name...", label_visibility="collapsed")
    with col_cat:
        categories = sorted({f.get("category", "other") for f in all_funcs})
        cat_options = ["All"] + categories
        selected_cat = st.selectbox("Category", cat_options, key="func_cat")

    # Filter
    funcs = all_funcs
    if query:
        q = query.lower()
        funcs = [f for f in funcs if q in f.get("name", "").lower() or q in f.get("description", "").lower()]
    if selected_cat != "All":
        funcs = [f for f in funcs if f.get("category", "") == selected_cat]

    st.caption(f"{len(funcs)} functions" + (f" matching '{esc(query)}'" if query else ""))

    if not funcs:
        st.info("No functions found.")
        return

    # Display as compact table
    for f in funcs[:50]:
        _render_function_row(f, theme)


def _render_function_row(func: dict, theme: ColorTokens) -> None:
    """Render a single function row in the library table."""
    name = esc(func.get("name", ""))
    category = func.get("category", "other")
    icon = CATEGORY_ICONS.get(category, "?")
    description = esc(func.get("description", ""))
    dialect_count = len(func.get("dialects", {}))

    with st.expander(f"**{name}** · `{icon}` {esc(category.title())} · {dialect_count} dialects", expanded=False):
        st.markdown(f"**{description}**")

        dialects = func.get("dialects", {})
        if dialects:
            st.markdown("**Syntax by Database:**")
            items = list(dialects.items())
            for i in range(0, len(items), 3):
                cols = st.columns(min(3, len(items) - i))
                for j, (dialect, syntax) in enumerate(items[i:i+3]):
                    with cols[j]:
                        st.markdown(
                            f'**{esc(dialect.upper())}**\n`{esc(syntax)}`'
                        )
