"""Lineage Workspace for SQL Dialect Master v2."""
from __future__ import annotations

import sqlglot
import streamlit as st

from frontend.app_context_v2 import DIALECTS, get_dialect_label
from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc
from frontend.core.viewmodels import (
    LineageOutputColumn,
    LineageTable,
    LineageViewModel,
    sanitize_mermaid_id,
    sanitize_mermaid_label,
)


def render_lineage_page(theme: ColorTokens) -> None:
    """Render the Lineage workspace."""

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">Lineage</div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Visualize table and column dependencies
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
        key="lineage_dialect",
    )

    sql = st.text_area(
        "SQL",
        key="lineage_sql",
        height=180,
        placeholder="SELECT u.name AS user_name, COUNT(o.id) AS order_count FROM users u LEFT JOIN orders o ON u.id = o.user_id GROUP BY u.name",
    )

    if st.button("Analyze", type="primary", key="lineage_analyze", use_container_width=True):
        if not sql.strip():
            st.warning("Please enter SQL to analyze.")
        else:
            try:
                vm = _build_lineage(sql, dialect)
                st.session_state.lineage_last_vm = vm
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Parse error: {esc(str(e))}")

    vm: LineageViewModel | None = st.session_state.get("lineage_last_vm")
    if vm is None:
        return

    col_diagram, col_details = st.columns([2, 1])

    with col_diagram:
        st.markdown("### Lineage Diagram")
        mermaid = _build_mermaid(vm)
        st.markdown(mermaid)

    with col_details:
        st.markdown("### Tables")
        for t in vm.tables:
            alias_str = f" as {esc(t.alias)}" if t.alias and t.alias != t.name else ""
            st.caption(f"`{esc(t.name)}`{alias_str}")

        st.markdown("### Output Columns")
        for oc in vm.output_columns:
            st.caption(f"`{esc(oc.name)}`")
            if oc.expression:
                st.caption(f"  Expr: {esc(oc.expression)}")

        if vm.column_references:
            st.markdown("### Column References")
            for tbl, cols in list(vm.column_references.items())[:5]:
                st.caption(f"**{esc(tbl)}**: {', '.join(esc(c) for c in cols)}")


def _build_lineage(sql: str, dialect: str) -> LineageViewModel:
    """Build a LineageViewModel from SQL using sqlglot AST."""
    parsed = sqlglot.parse_one(sql, read=dialect)

    # Extract tables
    tables = []
    seen = set()
    for t in parsed.find_all(sqlglot.exp.Table):
        name = t.name
        alias = t.alias or name
        if name not in seen:
            tables.append(LineageTable(name=name, alias=alias))
            seen.add(name)

    # Extract output columns from SELECT
    output_columns = []
    select = parsed.find(sqlglot.exp.Select)
    if select:
        for expr in select.expressions:
            alias = getattr(expr, 'alias', None)
            col_name = alias if alias else getattr(expr, 'name', None)
            if col_name:
                output_columns.append(LineageOutputColumn(
                    name=str(col_name),
                    expression=str(expr),
                ))

    # Extract column references
    col_refs: dict[str, list[str]] = {}
    for col in parsed.find_all(sqlglot.exp.Column):
        table_ref = col.table or "unknown"
        if table_ref not in col_refs:
            col_refs[table_ref] = []
        if col.name not in col_refs[table_ref]:
            col_refs[table_ref].append(col.name)

    return LineageViewModel(
        dialect=dialect,
        sql=sql,
        tables=tables,
        output_columns=output_columns,
        column_references=col_refs,
    )


def _build_mermaid(vm: LineageViewModel) -> str:
    """Build a Mermaid flowchart from LineageViewModel."""
    lines = ["```mermaid", "flowchart LR"]

    # Source tables
    lines.append("    subgraph sources[\"Sources\"]")
    for t in vm.tables:
        safe_id = sanitize_mermaid_id(t.name)
        lines.append(f"        {safe_id}[\"{esc(sanitize_mermaid_label(t.name))}\"]")
    lines.append("    end")

    # Query node
    lines.append('    QUERY{"SQL Query"}')

    # Output
    lines.append("    subgraph output[\"Output\"]")
    lines.append('        RESULT["Result Set"]')
    for oc in vm.output_columns[:6]:
        safe_id = sanitize_mermaid_id(oc.name)
        lines.append(f"        {safe_id}[\"{esc(sanitize_mermaid_label(oc.name))}\"]")
    lines.append("    end")

    # Edges
    for t in vm.tables:
        safe_id = sanitize_mermaid_id(t.name)
        lines.append(f"    {safe_id} --> QUERY")
    lines.append("    QUERY --> RESULT")
    for oc in vm.output_columns[:6]:
        safe_id = sanitize_mermaid_id(oc.name)
        lines.append(f"    RESULT --> {safe_id}")

    lines.append("```")
    return "\n".join(lines)
