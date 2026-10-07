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

    # Group by category (TEMPLATES maps category -> list of (label, sql)).
    categories: dict[str, list[tuple[str, str]]] = {}
    for cat, items in TEMPLATES.items():
        if isinstance(items, list):
            categories[cat] = list(items)
        else:
            categories[cat] = [(cat, items)]

    for cat, items in categories.items():
        st.markdown(f"##### {esc(cat)}")
        for label, sql in items:
            short_label = label.replace(f"{cat} · ", "")
            with st.expander(f"{esc(short_label)}", expanded=False):
                st.code(esc(sql), language="sql")
                st.button(
                    "Use in Convert",
                    key=_deterministic_key("tpl", f"{cat}::{label}"),
                    on_click=_load_template,
                    args=(sql,),
                )


def _deterministic_key(prefix: str, value: str) -> str:
    """Build a stable, process-independent widget key.

    ``str.hash`` is salted per process on CPython, so it must never be
    used for Streamlit widget keys.  The previous code also applied
    ``hash()`` to a list of template tuples, which is unhashable and
    crashed the page at runtime.
    """
    import hashlib

    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}"


def _load_template(sql: str) -> None:
    """Load a template SQL into the Convert workspace."""
    st.session_state.convert_src_sql = sql
    st.query_params["page"] = "convert"
