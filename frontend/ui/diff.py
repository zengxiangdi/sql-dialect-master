"""Semantic Diff UI components for SQL Dialect Master v2.

Renders the finding list, finding detail/inspector, and text diff view.
All data comes from SemanticDiffViewModel — no direct backend access.
"""
from __future__ import annotations

import streamlit as st

from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc
from frontend.core.viewmodels import (
    SemanticDiffViewModel,
    SemanticFindingViewModel,
)


def render_semantic_diff_workspace(
    vm: SemanticDiffViewModel,
    source_sql: str,
    target_sql: str,
    theme: ColorTokens,
    selected_finding_index: int | None = None,
) -> None:
    """Render the full Semantic Diff workspace with finding list and inspector.

    Args:
        vm: SemanticDiffViewModel from backend
        source_sql: Raw source SQL for display
        target_sql: Raw target SQL for display
        theme: Current theme tokens
        selected_finding_index: Index of selected finding (for inspector)
    """
    _render_overall_status(vm, theme)

    if vm.parse_error:
        st.error(f"Parse error: {esc(vm.parse_error)}")
        return

    col_findings, col_inspector = st.columns([2, 1])

    with col_findings:
        _render_finding_list(vm, selected_finding_index, theme)

    with col_inspector:
        if selected_finding_index is not None and 0 <= selected_finding_index < len(vm.findings):
            _render_finding_inspector(vm.findings[selected_finding_index], theme)
        else:
            _render_inspector_placeholder(theme)

    # Tabs for Semantic vs Text diff
    st.markdown("---")
    _render_diff_tabs(vm, source_sql, target_sql, theme)


def _render_overall_status(vm: SemanticDiffViewModel, theme: ColorTokens) -> None:
    """Render the overall semantic classification banner."""
    severity_colors = {
        "valid": theme.success,
        "warning": theme.warning,
        "error": theme.danger,
        "info": theme.info,
        "neutral": theme.text_muted,
    }
    color = severity_colors.get(vm.overall_status, theme.text_muted)

    # Finding summary
    summary_parts = []
    if vm.error_count:
        summary_parts.append(f"{vm.error_count} error{'s' if vm.error_count > 1 else ''}")
    if vm.warning_count:
        summary_parts.append(f"{vm.warning_count} warning{'s' if vm.warning_count > 1 else ''}")
    summary = " · ".join(summary_parts) if summary_parts else "No findings"

    st.markdown(
        f"""
        <div style="display:flex; align-items:center; justify-content:space-between;
                    padding:12px 16px; background:{color}12; border:1px solid {color}30;
                    border-radius:6px; margin-bottom:16px;">
            <div>
                <div style="font-size:11px; font-weight:600; letter-spacing:0.06em;
                            text-transform:uppercase; color:{color};">
                    {esc(vm.classification_label)}
                </div>
                <div style="font-size:12px; color:{theme.text_secondary}; margin-top:2px;">
                    {esc(vm.source_dialect)} → {esc(vm.target_dialect)} · {summary}
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:11px; color:{theme.text_muted};">confidence</div>
                <div style="font-size:18px; font-weight:700; color:{color}; font-family:monospace;">
                    {vm.confidence:.0%}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_finding_list(vm: SemanticDiffViewModel, selected_idx: int | None, theme: ColorTokens) -> None:
    """Render the findings list."""
    st.markdown(
        f'<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        f'text-transform:uppercase; color:{theme.text_muted}; margin-bottom:8px;">'
        f'Findings ({vm.finding_count})</div>',
        unsafe_allow_html=True,
    )

    if not vm.findings:
        st.info("No semantic differences detected.")
        return

    for i, finding in enumerate(vm.findings):
        is_selected = i == selected_idx
        bg = theme.selected_bg if is_selected else theme.surface
        border_color = theme.accent if is_selected else theme.border
        icon = "●" if finding.severity == "error" else "○"
        icon_color = theme.danger if finding.severity == "error" else theme.warning

        st.markdown(
            f"""
            <div class="sdm-finding-item" data-index="{i}"
                 style="padding:10px 12px; margin-bottom:4px; background:{bg};
                        border:1px solid {border_color}; border-radius:6px;
                        cursor:pointer; transition:all 0.15s;"
                 onmouseover="this.style.background='{theme.hover}'"
                 onmouseout="this.style.background='{bg}'">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                    <span style="color:{icon_color}; font-size:10px;">{icon}</span>
                    <span style="font-size:12px; font-weight:600; color:{theme.text_primary};">
                        {esc(finding.category_label)}
                    </span>
                    <span style="margin-left:auto; font-size:10px; font-weight:600;
                                 padding:2px 6px; border-radius:3px;
                                 background:{theme.danger}15; color:{theme.danger};">
                        {esc(finding.severity_label)}
                    </span>
                </div>
                <div style="font-size:11px; color:{theme.text_secondary}; line-height:1.4;">
                    {esc(finding.explanation[:100])}
                    {'...' if len(finding.explanation) > 100 else ''}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("Select", key=f"find_{i}", help=f"View {finding.category} finding details"):
            st.session_state.sdm_selected_finding_index = i
            st.rerun()


def _render_finding_inspector(finding: SemanticFindingViewModel, theme: ColorTokens) -> None:
    """Render the detail inspector for a selected finding."""
    st.markdown(
        f'<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        f'text-transform:uppercase; color:{theme.text_muted}; margin-bottom:12px;">'
        f'Finding #{finding.index + 1} · {esc(finding.category_label)}</div>',
        unsafe_allow_html=True,
    )

    # Severity badge
    sev_color = theme.danger if finding.severity == "error" else theme.warning
    st.markdown(
        f'<div style="display:inline-block; padding:3px 8px; border-radius:3px; '
        f'background:{sev_color}15; color:{sev_color}; font-size:11px; font-weight:600; '
        f'letter-spacing:0.05em; margin-bottom:12px;">'
        f'{esc(finding.severity_label)}</div>',
        unsafe_allow_html=True,
    )

    # Explanation
    st.markdown(
        '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        'text-transform:uppercase; color:' + theme.text_muted + '; margin:12px 0 6px;">'
        'Explanation</div>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div style="font-size:12px; color:{theme.text_primary}; line-height:1.6;">'
                f'{esc(finding.explanation)}</div>', unsafe_allow_html=True)

    # Source fragment
    st.markdown(
        '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        'text-transform:uppercase; color:' + theme.text_muted + '; margin:12px 0 6px;">'
        'Source Fragment</div>',
        unsafe_allow_html=True,
    )
    if finding.source_fragment:
        st.code(finding.source_fragment, language="sql")
    else:
        st.caption("Not available")

    # Target fragment
    st.markdown(
        '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
        'text-transform:uppercase; color:' + theme.text_muted + '; margin:12px 0 6px;">'
        'Target Fragment</div>',
        unsafe_allow_html=True,
    )
    if finding.target_fragment:
        st.code(finding.target_fragment, language="sql")
    else:
        st.caption("Not available")

    # Evidence
    if finding.evidence:
        st.markdown(
            '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
            'text-transform:uppercase; color:' + theme.text_muted + '; margin:12px 0 6px;">'
            'Evidence</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"`{esc(finding.evidence)}`")


def _render_inspector_placeholder(theme: ColorTokens) -> None:
    """Render the empty inspector state."""
    st.markdown(
        f"""
        <div style="padding:24px; border:1px dashed {theme.border}; border-radius:6px;
                    text-align:center; color:{theme.text_muted};">
            <div style="font-size:12px;">Select a finding to inspect details</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_diff_tabs(
    vm: SemanticDiffViewModel,
    source_sql: str,
    target_sql: str,
    theme: ColorTokens,
) -> None:
    """Render Semantic / Text diff tab switcher."""
    tab_sem, tab_txt = st.tabs(["Semantic", "Text"])

    with tab_sem:
        # Already rendered above — show source/target side by side
        col_s, col_t = st.columns(2)
        with col_s:
            st.markdown(
                '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
                'text-transform:uppercase; color:#' + theme.text_muted[1:] + '; margin-bottom:6px;">'
                'Source</div>',
                unsafe_allow_html=True,
            )
            st.code(source_sql, language="sql")
        with col_t:
            st.markdown(
                '<div style="font-size:11px; font-weight:600; letter-spacing:0.06em; '
                'text-transform:uppercase; color:#' + theme.text_muted[1:] + '; margin-bottom:6px;">'
                'Target</div>',
                unsafe_allow_html=True,
            )
            st.code(target_sql, language="sql")

    with tab_txt:
        import difflib
        diff_lines = list(
            difflib.unified_diff(
                source_sql.splitlines(),
                target_sql.splitlines(),
                fromfile=f"Source ({esc(vm.source_dialect)})",
                tofile=f"Target ({esc(vm.target_dialect)})",
                lineterm="",
            )
        )
        if diff_lines:
            diff_text = "\n".join(diff_lines)
            st.code(diff_text, language="diff")
        else:
            st.success("No textual differences found.")
