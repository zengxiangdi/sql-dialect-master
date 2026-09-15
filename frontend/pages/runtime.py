"""Runtime Verification page for SQL Dialect Master v2.

This page is a placeholder — real runtime verification requires a
connected database, which is not currently available in the Streamlit
environment. The UI clearly signals "not available" rather than
fabricating results.
"""
from __future__ import annotations

import streamlit as st

from frontend.core.design_tokens import ColorTokens


def render_runtime_page(theme: ColorTokens) -> None:
    """Render the Runtime Verification page."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                Runtime Verification
            </div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Execute SQL against connected databases to verify semantics
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Not available notice
    st.markdown(
        f"""
        <div style="padding:24px; border:1px dashed {theme.border}; border-radius:8px;
                    text-align:center; color:{theme.text_muted};">
            <div style="font-size:16px; font-weight:600; margin-bottom:8px;">
                Not Available
            </div>
            <div style="font-size:12px;">
                Runtime verification requires a connected database. This feature
                is available via the API when a database connection is configured.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Architecture info
    st.markdown("---")
    st.markdown("### Architecture")
    st.markdown(
        f"""
        <div style="font-size:12px; color:{theme.text_secondary}; line-height:1.8;">
            <p>When a database connection is available, the Runtime workspace will:</p>
            <ul style="margin:8px 0 8px 20px; padding:0;">
                <li>Execute source and target SQL against connected databases</li>
                <li>Compare result sets for semantic equivalence</li>
                <li>Report execution time and row count differences</li>
                <li>Flag cases where AST analysis was insufficient</li>
            </ul>
            <p style="color:{theme.text_muted};">Current status: No database connections configured.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
