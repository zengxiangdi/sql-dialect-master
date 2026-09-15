"""Type Mapping page for SQL Dialect Master v2."""
from __future__ import annotations

import streamlit as st

from frontend.app_context_v2 import DIALECTS, get_dialect_label
from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc

TYPE_CATEGORIES = {
    "String Types": ["STRING", "VARCHAR", "CHAR", "TEXT", "MEDIUMTEXT", "LONGTEXT"],
    "Numeric Types": ["BIGINT", "INT", "SMALLINT", "TINYINT", "DOUBLE", "FLOAT", "DECIMAL", "MONEY", "SERIAL"],
    "Boolean & Bit": ["BOOLEAN", "BIT"],
    "Date/Time Types": ["DATE", "TIME", "TIMESTAMP", "TIMESTAMP_TZ", "INTERVAL", "YEAR"],
    "Complex Types": ["ARRAY", "MAP", "STRUCT", "JSON", "JSONB", "XML"],
    "Binary Types": ["BINARY"],
    "Special Types": ["UUID", "INET", "GEOMETRY", "GEOGRAPHY", "ENUM", "SET"],
}


def render_types_page(types_data: dict, theme: ColorTokens) -> None:
    """Render the Type Mapping page."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                Type Mapping
            </div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Compare data types across database dialects
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    mappings = types_data.get("mappings", {})

    col_src, col_tgt = st.columns(2)
    with col_src:
        src_db = st.selectbox("Source", DIALECTS, index=DIALECTS.index("postgres") if "postgres" in DIALECTS else 0,
                               format_func=get_dialect_label, key="type_src")
    with col_tgt:
        tgt_db = st.selectbox("Target", DIALECTS, index=DIALECTS.index("mysql") if "mysql" in DIALECTS else 0,
                               format_func=get_dialect_label, key="type_tgt")

    st.markdown(f"**{esc(src_db.upper())}** → **{esc(tgt_db.upper())}**")

    # Build table data
    table_data = []
    for type_name, type_map in mappings.items():
        src_type = type_map.get(src_db, "N/A")
        tgt_type = type_map.get(tgt_db, "N/A")
        if src_type == tgt_type:
            status = "exact"
        elif tgt_type != "N/A":
            status = "mapped"
        else:
            status = "missing"
        table_data.append({
            "Type": type_name,
            esc(src_db.upper()): src_type,
            esc(tgt_db.upper()): tgt_type,
            "Status": status,
        })

    # Render as dataframe
    import pandas as pd
    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Detail explorer
    st.markdown("---")
    st.markdown("##### Type Details")

    col_cat, col_type = st.columns([1, 2])
    with col_cat:
        cat_options = ["All"] + list(TYPE_CATEGORIES.keys())
        selected_cat = st.selectbox("Category", cat_options, key="type_detail_cat")

    if selected_cat == "All":
        available = list(mappings.keys())
    else:
        available = [t for t in TYPE_CATEGORIES.get(selected_cat, []) if t in mappings]

    with col_type:
        selected_type = st.selectbox("Select Type", available, key="type_detail_sel")

    if selected_type and selected_type in mappings:
        m = mappings[selected_type]
        st.markdown(f"### `{esc(selected_type)}`")
        if "notes" in m:
            st.info(esc(m["notes"]))

        # Show all dialect mappings
        dialect_items = [(d, t) for d, t in m.items() if d != "notes"]
        for row_start in range(0, len(dialect_items), 4):
            cols = st.columns(min(4, len(dialect_items) - row_start))
            for j, (dialect, typ) in enumerate(dialect_items[row_start:row_start+4]):
                with cols[j]:
                    status_icon = "✓" if typ not in ["N/A", "JSON", "STRING"] else "⚠"
                    st.markdown(f"**{esc(dialect.upper())}**\n`{esc(typ)}` {status_icon}")
