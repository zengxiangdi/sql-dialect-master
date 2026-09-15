"""SQL editor component for SQL Dialect Master v2.

Provides a styled text area with monospace font, line-number-friendly
layout, and consistent styling across the application.
"""
from __future__ import annotations

import streamlit as st

from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc


def render_sql_editor(
    key: str,
    label: str,
    value: str = "",
    height: int = 240,
    dialect_key: str | None = None,
    placeholder: str = "Enter SQL query...",
    theme: ColorTokens | None = None,
    disabled: bool = False,
) -> str:
    """Render a styled SQL editor text area.

    Args:
        key: Streamlit widget key
        label: Display label above the editor
        value: Initial SQL text
        height: Editor height in pixels
        dialect_key: Optional key for dialect selector (shown alongside label)
        placeholder: Placeholder text
        theme: Current theme tokens (uses DARK default if None)
        disabled: Whether the editor is read-only

    Returns:
        The SQL text entered by the user (read from session state)
    """
    if theme is None:
        from frontend.core.design_tokens import DARK
        theme = DARK

    # Build label HTML
    label_html = f'<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; ' \
                 f'text-transform:uppercase; color:{theme.text_muted}; margin-bottom:6px;">' \
                 f'{esc(label)}</div>'

    # Dialect badge (if provided)
    dialect_badge = ""
    if dialect_key and dialect_key in st.session_state:
        dialect_val = esc(str(st.session_state[dialect_key]))
        dialect_badge = (
            f'<span style="font-family:monospace; font-size:11px; color:{theme.accent}; '
            f'background:{theme.selected_bg}; padding:2px 6px; border-radius:3px; '
            f'border:1px solid {theme.border}; margin-left:8px;">{dialect_val}</span>'
        )

    st.markdown(f"{label_html}{dialect_badge}")

    sql = st.text_area(
        key=key,
        value=value,
        height=height,
        placeholder=placeholder,
        label_visibility="collapsed",
        disabled=disabled,
        horizontal=True,
    )

    return sql


def render_code_display(sql: str, language: str = "sql", theme: ColorTokens | None = None) -> None:
    """Render SQL code in a styled code block.

    Args:
        sql: SQL text to display
        language: Syntax highlighting language
        theme: Current theme tokens
    """
    if theme is None:
        from frontend.core.design_tokens import DARK
        theme = DARK

    st.markdown(
        f"""
        <div style="border:1px solid {theme.border}; border-radius:6px; overflow:hidden;
                    background:{theme.input_bg};">
            <div style="display:flex; align-items:center; justify-content:space-between;
                        padding:6px 10px; background:{theme.surface}; border-bottom:1px solid {theme.border};
                        font-size:11px; font-weight:600; letter-spacing:0.06em; text-transform:uppercase;
                        color:{theme.text_muted};">
                <span>SQL</span>
                <span style="font-family:monospace; color:{theme.accent};">{esc(language)}</span>
            </div>
            <pre style="margin:0; padding:12px; background:{theme.input_bg};
                        color:{theme.text_primary}; font-family:monospace; font-size:13px;
                        line-height:1.6; white-space:pre; overflow:auto;">{esc(sql)}</pre>
        </div>
        """,
        unsafe_allow_html=True,
    )
