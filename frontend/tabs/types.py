#!/usr/bin/env python3
"""Type Mapping Tab Component.

Displays the Data Type Mapping Matrix, allowing users to:
- Compare type mappings between source and target dialects
- Explore types by category
- View detailed type support across all dialects
"""
import streamlit as st
from frontend.app_context import DIALECTS, DIALECT_INFO, get_dialect_label


def render_types_tab(types_data, current_theme):
    """Render the Type Mapping tab content."""
    
    st.markdown("#### 🗂️ Data Type Mapping Matrix")
    st.caption("Compare data types across 12 database dialects")
    
    mappings = types_data.get("mappings", {})
    
    # Database selector
    col_src_db, col_tgt_db = st.columns(2)
    with col_src_db:
        src_db = st.selectbox("From Database", DIALECTS, index=1, format_func=get_dialect_label, key="type_src")
    with col_tgt_db:
        tgt_db = st.selectbox("To Database", DIALECTS, index=0, format_func=get_dialect_label, key="type_tgt")
    
    # Build comparison table
    src_info = DIALECT_INFO.get(src_db, {})
    tgt_info = DIALECT_INFO.get(tgt_db, {})
    
    st.markdown(f"### {src_info.get('icon', '')} {src_db.upper()} → {tgt_info.get('icon', '')} {tgt_db.upper()}")
    
    table_data = []
    for type_name, type_map in mappings.items():
        src_type = type_map.get(src_db, "N/A")
        tgt_type = type_map.get(tgt_db, "N/A")
        status = "✅" if src_type == tgt_type else "🔄" if tgt_type != "N/A" else "⚠️"
        table_data.append({
            "Type": type_name,
            f"{src_db.upper()}": src_type,
            f"{tgt_db.upper()}": tgt_type,
            "Status": status
        })
    
    st.dataframe(table_data, use_container_width=True, hide_index=True)
    
    # Type detail explorer
    st.markdown("---")
    st.markdown("#### 🔍 Type Details")
    
    TYPE_CATEGORIES = {
        "String Types": ["STRING", "VARCHAR", "CHAR", "TEXT", "MEDIUMTEXT", "LONGTEXT"],
        "Numeric Types": ["BIGINT", "INT", "SMALLINT", "TINYINT", "DOUBLE", "FLOAT", "DECIMAL", "MONEY", "SERIAL"],
        "Boolean & Bit": ["BOOLEAN", "BIT"],
        "Date/Time Types": ["DATE", "TIME", "TIMESTAMP", "TIMESTAMP_TZ", "INTERVAL", "YEAR"],
        "Complex Types": ["ARRAY", "MAP", "STRUCT", "JSON", "JSONB", "XML"],
        "Binary Types": ["BINARY"],
        "Special Types": ["UUID", "INET", "GEOMETRY", "GEOGRAPHY", "ENUM", "SET"]
    }
    
    col_cat, col_type = st.columns([1, 2])
    with col_cat:
        type_category = st.selectbox("📂 Category", ["All Types"] + list(TYPE_CATEGORIES.keys()), key="type_cat")
    
    if type_category == "All Types":
        available_types = list(mappings.keys())
    else:
        available_types = [t for t in TYPE_CATEGORIES.get(type_category, []) if t in mappings]
    
    with col_type:
        type_sel = st.selectbox("🔍 Select Type", available_types, key="tsel")
    
    if type_sel and type_sel in mappings:
        m = mappings[type_sel]
        
        st.markdown(f"##### `{type_sel}`")
        
        if "notes" in m:
            st.info(f"📝 {m['notes']}")
        
        # Display all dialects
        dialect_items = [(d, t) for d, t in m.items() if d != "notes"]
        
        for row_start in range(0, len(dialect_items), 4):
            cols = st.columns(4)
            for col_idx, (dialect, typ) in enumerate(dialect_items[row_start:row_start+4]):
                info = DIALECT_INFO.get(dialect, {})
                status = "✅" if typ not in ["N/A", "JSON", "STRING"] else "⚠️"
                with cols[col_idx]:
                    st.markdown(f"""
                    <div style="background: {current_theme['secondary']}; padding: 10px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 1.2rem;">{info.get('icon', '📄')}</div>
                        <div style="font-weight: 600; font-size: 0.85rem;">{dialect.upper()}</div>
                        <code style="font-size: 0.75rem;">{typ}</code>
                        <div>{status}</div>
                    </div>
                    """, unsafe_allow_html=True)
