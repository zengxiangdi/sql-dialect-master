#!/usr/bin/env python3
"""Convert Tab Component.

Handles the main SQL conversion interface, including:
- Template selection
- Source/Target dialect selection
- SQL editor and formatting
- Conversion execution and results
- Analysis (Diff, Compatibility, Tips, Report)
- Batch conversion
"""
import streamlit as st
import re
import difflib
from datetime import datetime
from frontend.app_context import DIALECTS, convert, format_sql, get_dialect_label
from frontend.templates import TEMPLATES
from frontend.components import render_section_header


def render_convert_tab(current_theme):
    """Render the SQL Convert tab content."""

    st.markdown(
        render_section_header(
            "SQL 转换工作台",
            "优化布局、更清晰的操作分区，以及全局提示，帮助你更快完成转换",
            "⚡",
        ),
        unsafe_allow_html=True,
    )

    # Template selector with better UX
    st.markdown(render_section_header("快速开始", "选择模板或直接粘贴 SQL", "📋"), unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    template_choice = st.selectbox(
        "Choose a template or write your own SQL",
        list(TEMPLATES.keys()),
        key="tpl",
        label_visibility="collapsed"
    )
    default_sql = TEMPLATES.get(template_choice, "") or "SELECT * FROM users WHERE id = 1"
    st.caption("小贴士：模板会自动填充到源 SQL 输入框，可随时覆盖或编辑")
    st.markdown('</div>', unsafe_allow_html=True)

    # Load from history/favorites
    if st.session_state.get("load_sql"):
        loaded = st.session_state.load_sql
        default_sql = loaded["sql"]
        st.session_state.load_sql = None
    
    # Main conversion area
    col_src, col_arrow, col_tgt = st.columns([5, 1, 5])
    
    with col_src:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">🟢 Source</div>', unsafe_allow_html=True)
        st.caption("选择源库并可一键格式化 SQL")
        src_dialect = st.selectbox(
            "Source Database",
            DIALECTS,
            index=1,
            format_func=get_dialect_label,
            key="src"
        )
        src_sql = st.text_area(
            "Source SQL",
            default_sql, 
            height=220, 
            key="in",
            label_visibility="collapsed",
            placeholder="Enter your SQL query here..."
        )
        
        # Source actions
        col_fmt, col_clear = st.columns(2)
        with col_fmt:
            if st.button("✨ Format", key="fmt_src", use_container_width=True):
                formatted = format_sql(src_sql, src_dialect)
                st.session_state["formatted_src"] = formatted
                st.code(formatted, language="sql")
        with col_clear:
            if st.button("🗑️ Clear", key="clear_src", use_container_width=True):
                st.rerun()
        st.caption("快捷键: Ctrl+Shift+F 格式化 · 支持常见 12 种数据库")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_arrow:
        st.markdown("")
        st.markdown("")
        st.markdown("")
        st.markdown(f"""
        <div style="text-align: center; padding: 2rem 0;">
            <div style="font-size: 2rem; color: {current_theme['accent']};">→</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col_tgt:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">🎯 Target</div>', unsafe_allow_html=True)
        st.caption("选择目标库并立即执行转换")
        tgt_dialect = st.selectbox(
            "Target Database",
            DIALECTS,
            index=0,
            format_func=get_dialect_label,
            key="tgt"
        )

        # Convert button
        convert_clicked = st.button(
            "🚀 Convert SQL",
            type="primary", 
            use_container_width=True,
            key="convert_btn"
        )
        
        if convert_clicked:
            with st.spinner("Converting..."):
                r = convert(src_sql, src_dialect, tgt_dialect)

            if r["ok"]:
                st.session_state["last_sql"] = r["sql"]
                st.session_state["last_conversion"] = r
                
                # Add to history
                hist_entry = {"sql": src_sql, "src": src_dialect, "tgt": tgt_dialect, "result": r["sql"]}
                if hist_entry not in st.session_state.get("history", []):
                    st.session_state.history.append(hist_entry)
                
                # Success message
                st.success("✅ Conversion successful!")
                
                # Output SQL
                st.code(r["sql"], language="sql")

                # Action buttons
                st.markdown('<div class="panel" style="margin-top: 0.5rem;">', unsafe_allow_html=True)
                st.markdown('<div class="panel-title">⚙️ 操作</div>', unsafe_allow_html=True)
                col_copy, col_dl, col_fav = st.columns(3)
                with col_copy:
                    st.button("📋 Copy", key="copy_btn", use_container_width=True)
                    st.markdown(f'<textarea id="sql_copy" style="position:absolute;left:-9999px">{r["sql"]}</textarea><script>navigator.clipboard.writeText(document.getElementById("sql_copy").value)</script>', unsafe_allow_html=True)
                with col_dl:
                    st.download_button("📥 Download", r["sql"], "converted.sql", use_container_width=True)
                with col_fav:
                    if st.button("⭐ Favorite", key="fav_result", use_container_width=True):
                        if hist_entry not in st.session_state.get("favorites", []):
                            st.session_state.favorites.append(hist_entry)
                            st.toast("⭐ Added to favorites!")
                st.caption("提示：转换记录可在侧边栏快速回溯")
                st.markdown('</div>', unsafe_allow_html=True)

                # Transformation notes
                if r["notes"]:
                    st.markdown("##### 🔧 Transformations Applied")
                    for n in r["notes"]:
                        st.info(n)
            else:
                st.error(f"❌ Conversion failed: {r['err']}")
        st.markdown('</div>', unsafe_allow_html=True)

    # Detailed analysis section
    if st.session_state.get("last_conversion"):
        r = st.session_state["last_conversion"]

        st.markdown(render_section_header("转换分析", "查看差异、兼容性与优化提示", "📊"), unsafe_allow_html=True)
        st.markdown('<div class="panel">', unsafe_allow_html=True)

        analysis_tabs = st.tabs(["📝 Diff View", "⚠️ Compatibility", "💡 Tips", "📄 Report"])

        with analysis_tabs[0]:
            diff = difflib.unified_diff(
                src_sql.splitlines(), 
                r["sql"].splitlines(), 
                fromfile=f"Source ({src_dialect})", 
                tofile=f"Target ({tgt_dialect})", 
                lineterm=""
            )
            diff_text = "\n".join(diff)
            if diff_text:
                st.code(diff_text, language="diff")
            else:
                st.success("✅ No differences - SQL is identical!")
        
        with analysis_tabs[1]:
            compat_notes = []
            if tgt_dialect == "oracle":
                compat_notes.append("Oracle VARCHAR2 max 4000 chars (32767 with MAX_STRING_SIZE=EXTENDED)")
            if tgt_dialect == "mysql":
                compat_notes.append("MySQL DECIMAL max precision 65 digits")
            if tgt_dialect == "tsql":
                compat_notes.append("SQL Server DATETIME2 precision max 7 fractional digits")
            if src_dialect == "hive" and tgt_dialect in ["mysql", "postgres", "oracle"]:
                compat_notes.append("Hive ARRAY/MAP types converted to JSON - verify serialization")
            if "LIMIT" in src_sql.upper() and tgt_dialect == "oracle":
                compat_notes.append("Oracle uses FETCH FIRST n ROWS ONLY (12c+) or ROWNUM")
            
            if compat_notes:
                for note in compat_notes:
                    st.warning(f"⚠️ {note}")
            else:
                st.success("✅ No known compatibility issues")
        
        with analysis_tabs[2]:
            perf_tips = []
            if tgt_dialect == "hive":
                perf_tips.append("Consider adding DISTRIBUTE BY for large joins")
                perf_tips.append("Use CLUSTER BY for sorted output")
            if tgt_dialect == "spark":
                perf_tips.append("Use broadcast() hint for small dimension tables")
            if "JOIN" in src_sql.upper():
                perf_tips.append("Verify join keys have proper indexes/partitioning")
            if "GROUP BY" in src_sql.upper():
                perf_tips.append("Consider pre-aggregation for large datasets")
            
            if perf_tips:
                for tip in perf_tips:
                    st.info(f"💡 {tip}")
            else:
                st.success("✅ Query looks optimized!")
        
        with analysis_tabs[3]:
            report = f"""# SQL Conversion Report
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Tool:** SQL Dialect Master v1.0

## Summary
| Item | Value |
|------|-------|
| Source | {src_dialect.upper()} |
| Target | {tgt_dialect.upper()} |
| Status | ✅ Success |

## Source SQL
```sql
{src_sql}
```

## Target SQL
```sql
{r["sql"]}
```

## Transformations
{chr(10).join(['- ' + n for n in r["notes"]]) if r["notes"] else '- No special transformations'}
"""
            st.download_button("📥 Download Report", report, "conversion_report.md", mime="text/markdown", use_container_width=True)
            st.code(report, language="markdown")

        st.markdown('</div>', unsafe_allow_html=True)
    
    # Batch conversion
    with st.expander("📦 Batch Conversion"):
        st.caption("Convert multiple SQL statements at once")
        batch_sql = st.text_area(
            "Enter multiple SQL statements (separated by semicolons)",
            "SELECT * FROM users;\nSELECT * FROM orders WHERE status = 'active';",
            height=120,
            key="batch_sql"
        )
        
        col_batch_src, col_batch_tgt = st.columns(2)
        with col_batch_src:
            batch_src = st.selectbox("Source", DIALECTS, index=1, format_func=get_dialect_label, key="batch_src")
        with col_batch_tgt:
            batch_tgt = st.selectbox("Target", DIALECTS, index=0, format_func=get_dialect_label, key="batch_tgt")
        
        if st.button("🚀 Convert All", key="batch_btn", use_container_width=True):
            statements = [s.strip() for s in re.split(r';\s*\n?|\n', batch_sql) if s.strip()]
            results = []
            success_count = 0
            
            progress = st.progress(0)
            for i, stmt in enumerate(statements):
                r = convert(stmt, batch_src, batch_tgt)
                if r["ok"]:
                    results.append(f"-- Statement {i+1} ✅\n{r['sql']}")
                    success_count += 1
                else:
                    results.append(f"-- Statement {i+1} ❌ Error: {r['err']}\n-- Original: {stmt}")
                progress.progress((i + 1) / len(statements))
            
            st.success(f"✅ Converted {success_count}/{len(statements)} statements")
            combined_result = "\n\n".join(results)
            st.code(combined_result, language="sql")
            st.download_button("📥 Download All", combined_result, "batch_converted.sql", key="batch_dl")
