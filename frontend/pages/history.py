"""History page for SQL Dialect Master v2."""
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc


def render_history_page(theme: ColorTokens) -> None:
    """Render the History page."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                History
            </div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Recent conversions and saved queries
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    history: list[dict] = st.session_state.get("sdm_history", [])

    if not history:
        st.info("No conversion history yet.")
        return

    # Ensure each entry has a stable identity key
    for entry in history:
        if "identity" not in entry:
            import uuid
            entry["identity"] = str(uuid.uuid4())[:8]

    # Search and filter controls
    col_search, col_filter = st.columns([2, 1])
    with col_search:
        search = st.text_input("Search", key="hist_search", placeholder="Search SQL...", label_visibility="collapsed")
    with col_filter:
        filter_status = st.selectbox("Status", ["All", "Success", "Error"], key="hist_filter")

    # Apply filters
    filtered = history
    if search:
        s = search.lower()
        filtered = [h for h in filtered if s in h.get("sql", "").lower()]
    if filter_status == "Success":
        filtered = [h for h in filtered if h.get("status") == "valid"]
    elif filter_status == "Error":
        filtered = [h for h in filtered if h.get("status") == "error"]

    st.caption(f"{len(filtered)} entries")

    # Render entries
    for entry in filtered:
        _render_history_entry(entry, theme)


def _render_history_entry(entry: dict, theme: ColorTokens) -> None:
    """Render a single history entry."""
    src = esc(entry.get("src", "unknown"))
    tgt = esc(entry.get("tgt", "unknown"))
    sql_preview = esc(entry.get("sql", "")[:80])
    if len(entry.get("sql", "")) > 80:
        sql_preview += "..."
    status = entry.get("status", "neutral")
    created_at = entry.get("created_at", "")
    identity = entry.get("identity", "")

    # Status badge color
    if status == "valid":
        status_color = theme.success
        status_text = "✓ Valid"
    elif status == "error":
        status_color = theme.danger
        status_text = "✗ Error"
    else:
        status_color = theme.text_muted
        status_text = "—"

    # Time ago
    time_str = _format_time_ago(created_at) if created_at else "recent"

    with st.expander(f"{src} → {tgt} · {time_str}", expanded=False):
        st.markdown(
            f'<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">'
            f'<span style="color:{status_color}; font-size:11px; font-weight:600;">{status_text}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.code(sql_preview, language="sql")

        col_load, col_copy, col_fav, col_del = st.columns([1, 1, 1, 1])
        with col_load:
            if st.button("Load", key=f"hist_load_{identity}"):
                from frontend.core.navigation import create_navigation_intent
                intent = create_navigation_intent(
                    target_page="convert",
                    action="open_conversion",
                    sql=entry.get("sql", ""),
                    dialect=entry.get("src", "postgres"),
                    origin="history",
                )
                st.session_state.sdm_navigation_intent = intent
                st.rerun()
        with col_copy:
            if st.button("Copy", key=f"hist_copy_{identity}"):
                st.copy_button("Copy SQL", data=entry.get("sql", ""))
        with col_fav:
            favs: list[str] = st.session_state.get("sdm_favorites", [])
            if identity not in favs:
                if st.button("☆", key=f"hist_fav_{identity}"):
                    st.session_state.sdm_favorites.append(identity)
                    st.rerun()
            else:
                st.button("★", key=f"hist_fav_{identity}", disabled=True)
        with col_del:
            if st.button("Del", key=f"hist_del_{identity}"):
                history = st.session_state.sdm_history
                st.session_state.sdm_history = [h for h in history if h.get("identity") != identity]
                st.rerun()


def _format_time_ago(iso_str: str) -> str:
    """Format an ISO timestamp as 'X minutes ago' etc."""
    try:
        dt = datetime.fromisoformat(iso_str)
        delta = datetime.now(UTC) - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        elif seconds < 3600:
            return f"{seconds // 60}m ago"
        elif seconds < 86400:
            return f"{seconds // 3600}h ago"
        else:
            return f"{seconds // 86400}d ago"
    except (ValueError, TypeError):
        return "recent"
