"""Query Analysis (formerly Explain) Workspace for SQL Dialect Master v2.

This is static analysis only — no real execution plans are generated.
"""
from __future__ import annotations

import sqlglot
import streamlit as st

from frontend.app_context_v2 import DIALECTS, get_dialect_label
from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc


def render_query_analysis_page(theme: ColorTokens) -> None:
    """Render the Query Analysis workspace."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">
                Query Analysis
            </div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Static structural analysis of SQL queries
            </div>
            <div style="font-size:11px; color:{theme.warning}; margin-top:4px;">
                Note: This is static analysis only — not a real execution plan.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    dialect = st.selectbox(
        "SQL Dialect",
        DIALECTS,
        index=DIALECTS.index("postgres") if "postgres" in DIALECTS else 0,
        format_func=get_dialect_label,
        key="qa_dialect",
    )

    sql = st.text_area(
        "SQL",
        key="qa_sql",
        height=150,
        placeholder="SELECT u.name, COUNT(o.id) AS order_count FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.name ORDER BY order_count DESC LIMIT 10",
    )

    if st.button("Analyze", type="primary", key="qa_analyze", use_container_width=True):
        if not sql.strip():
            st.warning("Please enter SQL to analyze.")
        else:
            try:
                result = _analyze_sql(sql, dialect)
                st.session_state.qa_last_result = result
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Parse error: {esc(str(e))}")

    result = st.session_state.get("qa_last_result")
    if result is None:
        return

    # Display results
    cols = st.columns(4)
    with cols[0]:
        st.metric("Tables", len(result["tables"]))
    with cols[1]:
        st.metric("Joins", result["join_count"])
    with cols[2]:
        st.metric("Aggregation", "Yes" if result["has_aggregation"] else "No")
    with cols[3]:
        st.metric("Sorting", "Yes" if result["has_sorting"] else "No")

    if result["tables"]:
        st.markdown("##### Tables")
        for t in result["tables"]:
            st.caption(f"`{esc(t)}`")

    if result["hints"]:
        st.markdown("##### Dialect Hints")
        for hint in result["hints"][:5]:
            st.info(esc(hint))

    if result.get("limit"):
        st.markdown(f'**Limit:** `{esc(result["limit"])}`')


def _analyze_sql(sql: str, dialect: str) -> dict:
    """Perform static analysis on SQL."""
    parsed = sqlglot.parse_one(sql, read=dialect)

    tables = list({t.name for t in parsed.find_all(sqlglot.exp.Table)})
    joins = list(parsed.find_all(sqlglot.exp.Join))
    groups = list(parsed.find_all(sqlglot.exp.Group))
    orders = list(parsed.find_all(sqlglot.exp.Order))
    limit = parsed.find(sqlglot.exp.Limit)

    dialect_hints: dict[str, list[str]] = {
        "postgres": ["Seq/Index scan", "Hash/Merge join", "Parallel workers"],
        "mysql": ["Index scan", "Nested loop join", "InnoDB buffer pool"],
        "hive": ["MapReduce/Tez job", "Shuffle for GROUP BY"],
        "spark": ["Exchange shuffle", "HashAggregate", "Broadcast join"],
        "snowflake": ["Virtual warehouse", "Micro-partition pruning"],
        "duckdb": ["Vectorized execution", "Parallel pipeline"],
    }
    hints = dialect_hints.get(dialect, ["Standard processing"])

    return {
        "tables": tables,
        "join_count": len(joins),
        "has_aggregation": bool(groups),
        "has_sorting": bool(orders),
        "limit": str(limit.expression) if limit else None,
        "hints": hints,
    }
