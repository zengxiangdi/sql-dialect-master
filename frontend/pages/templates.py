"""Templates page for SQL Dialect Master v2."""
from __future__ import annotations

import streamlit as st

from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc
from frontend.templates_v2 import TEMPLATES


def render_templates_page(theme: ColorTokens) -> None:
    """Render the Templates page."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                Templates
            </div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Quick-start SQL templates by category
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Group by category
    categories: dict[str, list[tuple[str, str]]] = {}
    for name, sql in TEMPLATES.items():
        cat = name.split(" · ")[0] if " · " in name else "Other"
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((name, sql))

    for cat, items in categories.items():
        st.markdown(f"##### {esc(cat)}")
        for label, sql in items:
            short_label = label.replace(f"{cat} · ", "")
            with st.expander(f"{esc(short_label)}", expanded=False):
                st.code(esc(sql), language="sql")
                st.button("Use in Convert", key=f"tpl_{hash(sql) % 10000}",
                          on_click=_load_template, args=(sql,))


def _load_template(sql: str) -> None:
    """Load a template SQL into the Convert workspace."""
    st.session_state.convert_src_sql = sql
    st.query_params["page"] = "convert"
