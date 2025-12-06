#!/usr/bin/env python3
"""Execution Plan Tab Component.

Displays simulated execution plans for comparing query performance
across different database dialects.
"""
import streamlit as st
import sqlglot
from frontend.app_context import DIALECTS, DIALECT_INFO, get_dialect_label


def render_explain_tab(current_theme):
    """Render the Execution Plan Comparison tab content."""
    
    st.markdown("#### 📊 Execution Plan Comparison")
    st.caption("Compare how different databases would execute the same query")
    
    exp_sql = st.text_area(
        "SQL to analyze",
        "SELECT u.name, COUNT(o.id) AS order_count FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.name ORDER BY order_count DESC LIMIT 10",
        height=120,
        key="exp_sql",
        label_visibility="collapsed"
    )
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        exp_dialect1 = st.selectbox("Database 1", DIALECTS, index=1, format_func=get_dialect_label, key="exp_d1")
    with col_d2:
        exp_dialect2 = st.selectbox("Database 2", DIALECTS, index=0, format_func=get_dialect_label, key="exp_d2")
    
    if st.button("🔍 Compare Execution Plans", type="primary", key="exp_btn", use_container_width=True):
        def generate_explain(sql, dialect):
            try:
                parsed = sqlglot.parse_one(sql, read=dialect)
                tables = [t.name for t in parsed.find_all(sqlglot.exp.Table)]
                joins = list(parsed.find_all(sqlglot.exp.Join))
                groups = list(parsed.find_all(sqlglot.exp.Group))
                orders = list(parsed.find_all(sqlglot.exp.Order))
                limit = parsed.find(sqlglot.exp.Limit)
                
                info = DIALECT_INFO.get(dialect, {})
                
                plan = {
                    "dialect": dialect.upper(),
                    "icon": info.get('icon', '📄'),
                    "query_type": "SELECT",
                    "tables": tables,
                    "joins": len(joins),
                    "aggregation": bool(groups),
                    "sorting": bool(orders),
                    "limit": str(limit.expression) if limit else "None"
                }
                
                # Dialect-specific hints
                dialect_hints = {
                    "hive": ["MapReduce/Tez job", "Shuffle for GROUP BY", "ORC/Parquet scan", "Partition pruning"],
                    "mysql": ["Index scan", "Nested loop join", "Filesort", "InnoDB buffer pool"],
                    "postgres": ["Seq/Index scan", "Hash/Merge join", "Parallel workers", "Bitmap scan"],
                    "oracle": ["TABLE ACCESS", "HASH JOIN", "SORT ORDER BY", "Result cache"],
                    "spark": ["Exchange shuffle", "HashAggregate", "Broadcast join", "Adaptive execution"],
                    "tsql": ["Clustered index scan", "Hash match join", "Parallelism", "Columnstore"],
                    "trino": ["Distributed query", "Exchange operator", "Dynamic filtering", "Cost optimizer"],
                    "snowflake": ["Virtual warehouse", "Micro-partition pruning", "Result caching", "Auto clustering"],
                    "redshift": ["Columnar scan", "Zone maps", "Distribution key join", "Concurrency scaling"],
                    "clickhouse": ["MergeTree scan", "Primary key filter", "Vectorized execution", "Prewhere"],
                    "duckdb": ["Vectorized execution", "Parallel pipeline", "Adaptive radix tree", "Morsel parallelism"],
                    "databricks": ["Photon engine", "Delta optimization", "Z-ordering", "Dynamic file pruning"]
                }
                
                plan["hints"] = dialect_hints.get(dialect, ["Standard processing"])
                return plan
            except Exception as e:
                return {"error": str(e)}
        
        col_exp1, col_exp2 = st.columns(2)
        
        plan1 = generate_explain(exp_sql, exp_dialect1)
        plan2 = generate_explain(exp_sql, exp_dialect2)
        
        with col_exp1:
            if "error" not in plan1:
                st.markdown(f"""
                <div style="background: {current_theme['secondary']}; padding: 1.5rem; border-radius: 12px; border-left: 4px solid {current_theme['accent']};">
                    <h3 style="margin: 0 0 1rem 0;">{plan1['icon']} {plan1['dialect']}</h3>
                    <div style="display: grid; gap: 0.5rem;">
                        <div><strong>Query Type:</strong> {plan1['query_type']}</div>
                        <div><strong>Tables:</strong> {', '.join(plan1['tables'])}</div>
                        <div><strong>Joins:</strong> {plan1['joins']}</div>
                        <div><strong>Aggregation:</strong> {'Yes' if plan1['aggregation'] else 'No'}</div>
                        <div><strong>Sorting:</strong> {'Yes' if plan1['sorting'] else 'No'}</div>
                        <div><strong>Limit:</strong> {plan1['limit']}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("**Execution Hints:**")
                for hint in plan1['hints']:
                    st.info(f"💡 {hint}")
            else:
                st.error(f"Error: {plan1['error']}")
        
        with col_exp2:
            if "error" not in plan2:
                st.markdown(f"""
                <div style="background: {current_theme['secondary']}; padding: 1.5rem; border-radius: 12px; border-left: 4px solid {current_theme['success']};">
                    <h3 style="margin: 0 0 1rem 0;">{plan2['icon']} {plan2['dialect']}</h3>
                    <div style="display: grid; gap: 0.5rem;">
                        <div><strong>Query Type:</strong> {plan2['query_type']}</div>
                        <div><strong>Tables:</strong> {', '.join(plan2['tables'])}</div>
                        <div><strong>Joins:</strong> {plan2['joins']}</div>
                        <div><strong>Aggregation:</strong> {'Yes' if plan2['aggregation'] else 'No'}</div>
                        <div><strong>Sorting:</strong> {'Yes' if plan2['sorting'] else 'No'}</div>
                        <div><strong>Limit:</strong> {plan2['limit']}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("**Execution Hints:**")
                for hint in plan2['hints']:
                    st.info(f"💡 {hint}")
            else:
                st.error(f"Error: {plan2['error']}")
        
        st.caption("💡 This is a simulated execution plan. Connect to real databases for actual EXPLAIN output.")
