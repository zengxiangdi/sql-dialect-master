"""Lineage Workspace for SQL Dialect Master v2."""
from __future__ import annotations

import sqlglot
import streamlit as st

from frontend.app_context_v2 import DIALECTS, get_dialect_label
from frontend.core.design_tokens import ColorTokens
from frontend.core.escaping import esc
from frontend.core.fingerprints import input_fingerprint
from frontend.core.sql_inputs import parse_single_sql
from frontend.core.state import SessionState
from frontend.core.viewmodels import (
    LineageOutputColumn,
    LineageTable,
    LineageViewModel,
    sanitize_mermaid_id,
    sanitize_mermaid_label,
)


def render_lineage_page(theme: ColorTokens) -> None:
    """Render the Lineage workspace."""
    state = SessionState.get()

    st.markdown(
        f"""
        <div style="padding:12px 0; margin-bottom:16px; border-bottom:1px solid {theme.border};">
            <div style="font-size:18px; font-weight:700; color:{theme.text_primary};">Lineage</div>
            <div style="font-size:12px; color:{theme.text_muted}; margin-top:2px;">
                Table dependencies and column references from AST analysis
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

    fingerprint = input_fingerprint(sql, dialect)
    if state.get_raw("lineage_last_fingerprint") != fingerprint:
        state.lineage_last_vm = None

    if st.button("Analyze", type="primary", key="lineage_analyze", use_container_width=True):
        state.lineage_last_vm = None
        if not sql.strip():
            st.warning("Please enter SQL to analyze.")
        else:
            try:
                vm = _build_lineage(sql, dialect)
                state.lineage_last_vm = vm
                state.set_raw("lineage_last_fingerprint", fingerprint)
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Parse error: {esc(str(e))}")

    vm: LineageViewModel | None = state.lineage_last_vm
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
    parsed = parse_single_sql(sql, dialect)

    # Extract tables
    tables = []
    seen: set[tuple[str, str]] = set()
    for t in parsed.find_all(sqlglot.exp.Table):
        name = t.name
        # Preserve catalog/schema qualification in the display label.  The
        # alias remains the node identity for joins and self-joins.
        qualifiers = [str(part) for part in (getattr(t, "catalog", None), getattr(t, "db", None), name) if part]
        name = ".".join(qualifiers)
        alias = t.alias or name
        identity = (name, alias)
        if identity not in seen:
            tables.append(LineageTable(name=name, alias=alias, node_id=f"table_{len(tables)}"))
            seen.add(identity)

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
                    node_id=f"column_{len(output_columns)}",
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
    table_ids: dict[int, str] = {}
    for i, t in enumerate(vm.tables):
        safe_id = sanitize_mermaid_id(t.node_id or f"table_{i}")
        table_ids[i] = safe_id
        label = t.name if not t.alias or t.alias == t.name else f"{t.name} ({t.alias})"
        lines.append(f"        {safe_id}[\"{esc(sanitize_mermaid_label(label))}\"]")
    lines.append("    end")

    # Query node
    lines.append('    QUERY{"SQL Query"}')

    # Output
    lines.append("    subgraph output[\"Output\"]")
    lines.append('        RESULT["Result Set"]')
    output_ids: dict[int, str] = {}
    for i, oc in enumerate(vm.output_columns[:6]):
        safe_id = sanitize_mermaid_id(oc.node_id or f"column_{i}")
        output_ids[i] = safe_id
        lines.append(f"        {safe_id}[\"{esc(sanitize_mermaid_label(oc.name))}\"]")
    lines.append("    end")

    # Edges
    for safe_id in table_ids.values():
        lines.append(f"    {safe_id} --> QUERY")
    lines.append("    QUERY --> RESULT")
    for safe_id in output_ids.values():
        lines.append(f"    RESULT --> {safe_id}")

    lines.append("```")
    return "\n".join(lines)
