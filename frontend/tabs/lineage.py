#!/usr/bin/env python3
"""Lineage Tab Component.

Handles SQL Lineage visualization using Mermaid diagrams.
"""
import streamlit as st
import sqlglot
from frontend.app_context import DIALECTS, DIALECT_INFO, get_dialect_label


def render_lineage_tab(current_theme):
    """Render the SQL Lineage tab content."""
    
    st.markdown("#### 🔗 SQL Lineage Visualization")
    st.caption("Visualize table and column dependencies in your SQL")
    
    col_dialect, col_analyze = st.columns([2, 1])
    with col_dialect:
        lineage_dialect = st.selectbox("SQL Dialect", DIALECTS, index=1, format_func=get_dialect_label, key="lin_dialect")
    
    lineage_sql = st.text_area(
        "SQL to analyze",
        """SELECT 
    u.name AS user_name,
    u.email,
    COUNT(o.id) AS order_count,
    SUM(o.amount) AS total_amount
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
LEFT JOIN products p ON o.product_id = p.id
WHERE u.status = 'active'
GROUP BY u.name, u.email""",
        height=180,
        key="lin_sql",
        label_visibility="collapsed"
    )
    
    if st.button("🔍 Generate Lineage", type="primary", key="lin_btn", use_container_width=True):
        try:
            parsed = sqlglot.parse_one(lineage_sql, read=lineage_dialect)
            
            # Extract tables
            tables = []
            for t in parsed.find_all(sqlglot.exp.Table):
                alias = t.alias or t.name
                tables.append({"name": t.name, "alias": alias})
            
            # Extract columns
            columns = []
            for col in parsed.find_all(sqlglot.exp.Column):
                table_ref = col.table or "unknown"
                columns.append({"name": col.name, "table": table_ref})
            
            # Extract output columns
            output_cols = []
            select = parsed.find(sqlglot.exp.Select)
            if select:
                for expr in select.expressions:
                    if hasattr(expr, 'alias') and expr.alias:
                        output_cols.append(expr.alias)
                    elif hasattr(expr, 'name'):
                        output_cols.append(expr.name)
            
            # Display results
            col_diagram, col_details = st.columns([2, 1])
            
            with col_diagram:
                st.markdown("##### 📊 Lineage Diagram")
                
                # Build Mermaid diagram
                mermaid = "```mermaid\nflowchart LR\n"
                mermaid += "    subgraph Sources[\"📥 Source Tables\"]\n"
                for t in tables:
                    mermaid += f"        {t['name']}[(\"{t['name']}\")]\n"
                mermaid += "    end\n\n"
                
                mermaid += "    subgraph Transform[\"⚙️ Transformation\"]\n"
                mermaid += "        QUERY{{\"SQL Query\"}}\n"
                mermaid += "    end\n\n"
                
                mermaid += "    subgraph Output[\"📤 Output\"]\n"
                mermaid += "        RESULT[\"Result Set\"]\n"
                for oc in output_cols[:6]:
                    safe_name = oc.replace(' ', '_').replace('-', '_')
                    mermaid += f"        {safe_name}[\"{oc}\"]\n"
                mermaid += "    end\n\n"
                
                # Edges
                for t in tables:
                    mermaid += f"    {t['name']} --> QUERY\n"
                mermaid += "    QUERY --> RESULT\n"
                for oc in output_cols[:6]:
                    safe_name = oc.replace(' ', '_').replace('-', '_')
                    mermaid += f"    RESULT --> {safe_name}\n"
                
                mermaid += "```"
                
                st.markdown(mermaid)
            
            with col_details:
                st.markdown("##### 📋 Analysis")
                
                # Source tables
                st.markdown("**Source Tables:**")
                for t in tables:
                    info = DIALECT_INFO.get(lineage_dialect, {})
                    st.markdown(f"""
                    <div style="background: {current_theme['secondary']}; padding: 8px 12px; border-radius: 8px; margin-bottom: 4px;">
                        <code>{t['name']}</code>
                        {f"<span style='opacity: 0.6;'> as {t['alias']}</span>" if t['alias'] != t['name'] else ""}
                    </div>
                    """, unsafe_allow_html=True)
                
                # Output columns
                st.markdown("**Output Columns:**")
                for oc in output_cols:
                    st.code(oc)
                
                # Column references
                st.markdown("**Column References:**")
                col_refs = {}
                for c in columns:
                    key = c['table']
                    if key not in col_refs:
                        col_refs[key] = []
                    if c['name'] not in col_refs[key]:
                        col_refs[key].append(c['name'])
                
                for tbl, cols in col_refs.items():
                    st.caption(f"**{tbl}**: {', '.join(cols)}")
            
            # Export options
            with st.expander("📋 Export Mermaid Code"):
                clean_mermaid = mermaid.replace("```mermaid\n", "").replace("\n```", "")
                st.code(clean_mermaid, language="text")
                st.download_button("📥 Download", clean_mermaid, "lineage.mmd", use_container_width=True)
                
        except Exception as e:
            st.error(f"❌ Error parsing SQL: {e}")
