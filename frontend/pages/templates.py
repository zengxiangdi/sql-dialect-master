"""Templates page for SQL Dialect Master v2."""
from __future__ import annotations

import streamlit as st

from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc
from frontend.core.navigation import create_navigation_intent
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
                # st.code renders its argument literally — pass the raw
                # SQL; HTML escaping is only for markdown/HTML regions.
                st.code(sql, language="sql")
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
    # Route through the same handoff contract as History and NL2SQL.  Main
    # clears stale conversion output and applies both dialect widget values
    # before the Convert page creates them.
    source_dialect = st.session_state.get("convert_src", "postgres")
    target_dialect = st.session_state.get("convert_tgt", "mysql")
    if not isinstance(source_dialect, str) or not source_dialect:
        source_dialect = "postgres"
    if not isinstance(target_dialect, str) or not target_dialect:
        target_dialect = "mysql"
    st.session_state.sdm_navigation_intent = create_navigation_intent(
        target_page="convert",
        action="open_conversion",
        sql=sql,
        dialect=source_dialect,
        target_dialect=target_dialect,
        origin="templates",
    )
    st.query_params["page"] = "convert"
