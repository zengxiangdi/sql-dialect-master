#!/usr/bin/env python3
"""Function Encyclopedia Tab Component.

Displays the SQL function encyclopedia, allowing users to:
- Search and filter functions
- Compare syntax across 12 dialects
- View function descriptions and categories
"""
import streamlit as st
from frontend.app_context import DIALECT_INFO


def render_functions_tab(funcs_data, current_theme):
    """Render the Function Encyclopedia tab content."""
    
    st.markdown("#### 📚 SQL Function Encyclopedia")
    st.caption("Search and compare SQL functions across 12 database dialects")
    
    # Category emoji mapping
    CATEGORY_EMOJI = {
        "string": "📝 String",
        "date": "📅 Date/Time",
        "math": "🔢 Math",
        "aggregate": "📊 Aggregate",
        "window": "🪟 Window",
        "conditional": "❓ Conditional",
        "conversion": "🔄 Conversion",
        "json": "📋 JSON",
        "array": "📦 Array",
        "system": "⚙️ System",
        "geo": "🌍 Geospatial"
    }
    
    all_funcs = funcs_data.get("functions", [])
    raw_categories = sorted(set(f.get("category", "other") for f in all_funcs))
    categories = [CATEGORY_EMOJI.get(c, c.title()) for c in raw_categories]
    category_map = dict(zip(categories, raw_categories))
    
    # Search and filter controls
    col_search, col_cat = st.columns([2, 1])
    with col_search:
        q = st.text_input(
            "🔍 Search functions",
            "",
            key="fsearch",
            placeholder="Type function name or keyword..."
        )
    with col_cat:
        cat_options = ["All Categories"] + categories
        selected_cat = st.selectbox("📂 Category", cat_options, key="fcat")
    
    # Filter functions
    funcs = all_funcs
    if q:
        funcs = [f for f in funcs if q.lower() in f["name"].lower() or q.lower() in f.get("description", "").lower()]
    if selected_cat != "All Categories":
        raw_cat = category_map.get(selected_cat, selected_cat)
        funcs = [f for f in funcs if f.get("category", "") == raw_cat]
    
    # Results count
    st.caption(f"📊 Found {len(funcs)} functions" + (f" matching '{q}'" if q else ""))
    
    if funcs:
        # Display functions in a grid-like layout
        for f in funcs[:30]:  # Limit display
            cat_display = CATEGORY_EMOJI.get(f.get('category', ''), f.get('category', ''))
            
            with st.expander(f"**{f['name']}** · {f.get('description', '')} · `{cat_display}`"):
                st.markdown(f"**Description:** {f.get('description', 'No description available')}")
                
                # Show dialects in a clean grid
                dialects = f.get("dialects", {})
                if dialects:
                    st.markdown("**Syntax by Database:**")
                    
                    # Create 3-column layout
                    dialect_items = list(dialects.items())
                    for row_start in range(0, len(dialect_items), 3):
                        cols = st.columns(3)
                        for col_idx, (dialect, syntax) in enumerate(dialect_items[row_start:row_start+3]):
                            info = DIALECT_INFO.get(dialect, {})
                            with cols[col_idx]:
                                st.markdown(f"""
                                <div style="background: {current_theme['secondary']}; padding: 8px 12px; border-radius: 8px; margin-bottom: 4px;">
                                    <div style="font-weight: 600; font-size: 0.85rem;">{info.get('icon', '📄')} {dialect.upper()}</div>
                                    <code style="font-size: 0.8rem;">{syntax}</code>
                                </div>
                                """, unsafe_allow_html=True)
                    
                    st.caption(f"✅ Supported in {len(dialects)} databases")
    else:
        st.warning("No functions found. Try a different search term.")
