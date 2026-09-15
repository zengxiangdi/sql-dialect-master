"""Status and result display components for SQL Dialect Master v2."""
from __future__ import annotations

import streamlit as st

from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc


def render_conversion_status(
    status: str,
    label: str,
    detail: str | None = None,
    theme: ColorTokens | None = None,
) -> None:
    """Render a single status indicator row.

    Args:
        status: One of 'valid', 'warning', 'error', 'info', 'neutral'
        label: Status label text
        detail: Optional detail text
        theme: Current theme tokens
    """
    if theme is None:
        from frontend.core.design_tokens import DARK
        theme = DARK

    colors = {
        "valid": theme.success,
        "warning": theme.warning,
        "error": theme.danger,
        "info": theme.info,
        "neutral": theme.text_muted,
    }
    dots = {"valid": "●", "warning": "●", "error": "●", "info": "●", "neutral": "●"}
    dot_color = colors.get(status, theme.text_muted)
    dot = dots.get(status, "●")

    detail_html = f'<span style="color:{theme.text_secondary}; font-size:12px;"> — {esc(detail)}</span>' if detail else ""

    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:8px; padding:6px 0;">
            <span style="color:{dot_color}; font-size:10px;">{dot}</span>
            <span style="font-size:12px; color:{theme.text_primary};">{esc(label)}</span>
            {detail_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_result_panel(
    sql: str,
    source_dialect: str,
    target_dialect: str,
    warnings: list[str],
    transformations: list[str],
    compatibility_notes: list[str],
    error_message: str | None,
    semantic_label: str,
    semantic_status: str,
    theme: ColorTokens | None = None,
) -> None:
    """Render the full conversion result panel.

    Args:
        sql: Converted SQL
        source_dialect: Source dialect name
        target_dialect: Target dialect name
        warnings: List of warning strings
        transformations: List of transformation descriptions
        compatibility_notes: List of compatibility notes
        error_message: Error message if conversion failed
        semantic_label: Semantic status label (e.g. "Equivalent")
        semantic_status: Semantic status key for color
        theme: Current theme tokens
    """
    if theme is None:
        from frontend.core.design_tokens import DARK
        theme = DARK

    # Status badge
    status_colors = {
        "valid": (theme.success, f"background:{theme.success}15; color:{theme.success}; border-color:{theme.success}40;"),
        "error": (theme.danger, f"background:{theme.danger}15; color:{theme.danger}; border-color:{theme.danger}40;"),
        "warning": (theme.warning, f"background:{theme.warning}15; color:{theme.warning}; border-color:{theme.warning}40;"),
    }
    badge_style = status_colors.get(semantic_status, (theme.text_muted, f"background:{theme.hover}; color:{theme.text_muted}; border-color:{theme.border};"))[1]
    badge_text = esc(semantic_label) if semantic_status != "pending" else "Pending"

    if error_message:
        # Error state
        st.markdown(
            f"""
            <div style="padding:12px 14px; background:{theme.danger}12; border:1px solid {theme.danger}40;
                        border-radius:6px; margin-bottom:16px;">
                <div style="font-size:12px; font-weight:600; color:{theme.danger}; margin-bottom:4px;">
                    Conversion Failed
                </div>
                <div style="font-size:12px; color:{theme.text_secondary};">{esc(error_message)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # Success state with result panel
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; justify-content:space-between;
                    margin-bottom:12px;">
            <div style="font-size:12px; font-weight:600; letter-spacing:0.06em;
                        text-transform:uppercase; color:{theme.text_muted};">
                Conversion Result
            </div>
            <span style="font-size:11px; font-weight:600; padding:3px 8px; border-radius:4px;
                         border:1px solid {theme.border}; {badge_style};">
                {badge_text}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # SQL output
    st.code(sql, language="sql")

    # Action buttons
    col_copy, col_dl, col_diff = st.columns([1, 1, 1])
    with col_copy:
        st.copy_button("Copy", key=f"copy_result_{hash(sql) % 10000}", data=sql)
    with col_dl:
        st.download_button("Download", sql, "converted.sql", mime="text/sql")
    with col_diff:
        if st.button("Semantic Diff", key="to_diff_btn"):
            from frontend.core.navigation import create_navigation_intent
            intent = create_navigation_intent(
                target_page="diff",
                action="open_diff",
                source=sql,
                target=sql,
                src_dialect=source_dialect,
                tgt_dialect=target_dialect,
            )
            st.session_state.sdm_navigation_intent = intent
            st.rerun()

    # Transformations
    if transformations:
        st.markdown(
            f'<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            f'text-transform:uppercase; color:{theme.text_muted}; margin:16px 0 8px;">'
            f'Transformations</div>',
            unsafe_allow_html=True,
        )
        for t in transformations:
            st.caption(f"→ {esc(t)}")

    # Warnings
    if warnings:
        st.markdown(
            f'<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            f'text-transform:uppercase; color:{theme.text_muted}; margin:16px 0 8px;">'
            f'Warnings ({len(warnings)})</div>',
            unsafe_allow_html=True,
        )
        for w in warnings:
            st.warning(esc(w))

    # Compatibility notes
    if compatibility_notes:
        st.markdown(
            f'<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            f'text-transform:uppercase; color:{theme.text_muted}; margin:16px 0 8px;">'
            f'Compatibility Notes</div>',
            unsafe_allow_html=True,
        )
        for note in compatibility_notes:
            st.info(esc(note))


def render_batch_result(
    total: int,
    succeeded: int,
    failed: int,
    items: list,
    theme: ColorTokens | None = None,
) -> None:
    """Render batch conversion results.

    Args:
        total: Total statements processed
        succeeded: Number of successful conversions
        failed: Number of failed conversions
        items: List of BatchResultItem view models
        theme: Current theme tokens
    """
    if theme is None:
        from frontend.core.design_tokens import DARK
        theme = DARK

    rate = succeeded / total if total else 0

    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:16px; margin-bottom:12px;">
            <span style="font-size:13px; font-weight:500; color:{theme.text_primary};">
                {succeeded}/{total} statements converted
            </span>
            <div style="flex:1; height:4px; background:{theme.border}; border-radius:2px; overflow:hidden;">
                <div style="width:{rate*100}%; height:100%; background:{theme.success}; border-radius:2px;"></div>
            </div>
            {f'<span style="font-size:12px; color:{theme.danger};">{failed} failed</span>' if failed else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )

    for item in items:
        if item.success:
            with st.expander(f"Statement {item.statement_index} ✓", expanded=False):
                st.code(item.converted_sql or "", language="sql")
                if item.warnings:
                    for w in item.warnings:
                        st.caption(f"⚠ {esc(w)}")
        else:
            with st.expander(f"Statement {item.statement_index} ✗ Error", expanded=False):
                st.error(f"Error: {esc(item.error or 'Unknown error')}")
                st.caption("Original:")
                st.code(item.original_sql, language="sql")
