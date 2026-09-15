"""Semantic diff display component for SQL Dialect Master v2."""
from __future__ import annotations

import difflib

import streamlit as st

from frontend.core.design_tokens import SEMANTIC_STATUS_COLOR, ColorTokens
from frontend.core.escaping import esc


def render_semantic_diff_view(
    source_sql: str,
    target_sql: str,
    source_dialect: str,
    target_dialect: str,
    semantic_classification: str,
    structured_differences: list,
    differences: list[str],
    confidence: float,
    theme: ColorTokens | None = None,
) -> None:
    """Render the semantic diff workspace.

    Args:
        source_sql: Original SQL
        target_sql: Converted SQL
        source_dialect: Source dialect
        target_dialect: Target dialect
        semantic_classification: One of the semantic classification strings
        structured_differences: List of StructuredSemanticDifference objects
        differences: List of diff detail strings
        confidence: Confidence score 0-1
        theme: Current theme tokens
    """
    if theme is None:
        from frontend.core.design_tokens import DARK
        theme = DARK

    color_key = SEMANTIC_STATUS_COLOR.get(semantic_classification, "neutral")
    color = getattr(theme, color_key, theme.text_muted)

    # Classification header
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:20px;">
            <div style="font-size:20px; font-weight:700; color:{color};">
                {esc(semantic_classification.replace('_', ' ').title())}
            </div>
            <div style="font-size:12px; color:{theme.text_muted}; font-family:monospace;">
                confidence: {confidence:.0%}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Structured findings
    if structured_differences:
        st.markdown(
            '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            'text-transform:uppercase; color:' + theme.text_muted + '; margin-bottom:8px;">'
            'Findings</div>',
            unsafe_allow_html=True,
        )
        for diff in structured_differences:
            _render_finding(diff, theme)

    # Text diff fallback
    if differences:
        st.markdown(
            '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            'text-transform:uppercase; color:' + theme.text_muted + '; margin:16px 0 8px;">'
            'Canonical SQL Diff</div>',
            unsafe_allow_html=True,
        )
        diff_lines = [line for diff in differences for line in diff.splitlines() if line.startswith(("+", "-", " "))]
        if diff_lines:
            diff_text = "\n".join(diff_lines)
            st.code(diff_text, language="diff")


def _render_finding(diff, theme: ColorTokens) -> None:
    """Render a single structured semantic difference."""
    severity_colors = {
        "error": theme.danger,
        "warning": theme.warning,
    }
    sev = getattr(diff, 'severity', 'warning')
    sev_color = severity_colors.get(sev, theme.warning)
    sev_label = sev.upper()

    st.markdown(
        f"""
        <div style="border:1px solid {sev_color}40; border-radius:6px; padding:12px;
                    margin-bottom:8px; background:{sev_color}08;">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                <span style="font-size:11px; font-weight:700; color:{sev_color};
                             text-transform:uppercase; letter-spacing:0.05em;">
                    {esc(sev_label)}
                </span>
                <span style="font-size:11px; font-weight:600; letter-spacing:0.06em;
                             text-transform:uppercase; color:{theme.text_muted};">
                    {esc(getattr(diff, 'category', 'unknown'))}
                </span>
            </div>
            <div style="font-size:12px; color:{theme.text_primary}; margin-bottom:8px;">
                {esc(getattr(diff, 'explanation', ''))}
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                <div>
                    <div style="font-size:10px; font-weight:600; text-transform:uppercase;
                                letter-spacing:0.06em; color:{theme.text_muted}; margin-bottom:4px;">
                        Source
                    </div>
                    <code style="font-size:11px; color:{theme.text_secondary};
                                 font-family:monospace; background:{theme.input_bg};
                                 padding:4px 6px; border-radius:3px; display:block;
                                 white-space:pre-wrap; word-break:break-all;">
                        {esc(getattr(diff, 'source_fragment', ''))}
                    </code>
                </div>
                <div>
                    <div style="font-size:10px; font-weight:600; text-transform:uppercase;
                                letter-spacing:0.06em; color:{theme.text_muted}; margin-bottom:4px;">
                        Target
                    </div>
                    <code style="font-size:11px; color:{theme.text_secondary};
                                 font-family:monospace; background:{theme.input_bg};
                                 padding:4px 6px; border-radius:3px; display:block;
                                 white-space:pre-wrap; word-break:break-all;">
                        {esc(getattr(diff, 'target_fragment', ''))}
                    </code>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_text_diff(
    source_sql: str,
    target_sql: str,
    source_label: str,
    target_label: str,
    theme: ColorTokens | None = None,
) -> None:
    """Render a simple text-level diff between two SQL strings."""
    if theme is None:
        from frontend.core.design_tokens import DARK
        theme = DARK

    diff = difflib.unified_diff(
        source_sql.splitlines(),
        target_sql.splitlines(),
        fromfile=f"Source ({esc(source_label)})",
        tofile=f"Target ({esc(target_label)})",
        lineterm="",
    )
    diff_text = "\n".join(diff)
    if diff_text:
        st.code(diff_text, language="diff")
    else:
        st.success("No differences found — SQL is textually identical.")
