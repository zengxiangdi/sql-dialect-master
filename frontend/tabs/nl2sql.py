#!/usr/bin/env python3
"""NL2SQL Tab Component.

Handles Natural Language to SQL generation, including:
- Natural language input
- Dialect selection
- Table hints
- SQL generation and explanation
- Confidence scoring
"""
import streamlit as st
from frontend.app_context import DIALECTS, get_dialect_label
from frontend.components import render_section_header


def render_nl2sql_tab():
    """Render the NL2SQL tab content."""

    st.markdown(
        render_section_header(
            "自然语言生成 SQL",
            "描述业务意图即可生成 SQL，新增强调区块和更清晰的提示",
            "💬",
        ),
        unsafe_allow_html=True,
    )
    st.caption("Describe your query in Chinese or English, and we'll generate the SQL for you")
    
    # Example queries with better organization
    nl_examples = {
        "-- 选择示例 / Select Example --": "",
        "📊 统计类 / Aggregation": "统计所有用户的数量",
        "📅 时间筛选 / Date Filter": "查询最近7天的订单",
        "💰 条件筛选 / Condition": "查询金额大于100的订单",
        "👥 分组统计 / Group By": "按部门分组统计员工数量",
        "🔝 排序限制 / Order & Limit": "查询前10个用户按得分降序排列",
        "🔗 关联查询 / Join": "查询用户和订单关联的数据",
        "📈 平均值 / Average": "查询员工的平均薪资",
        "🔍 模糊搜索 / Like": "查询名字包含'张'的用户",
        "📆 本月数据 / This Month": "查询本月所有订单的总金额",
        "🏆 Top N / Ranking": "查询销售额最高的前5个产品",
    }
    
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    col_example, col_dialect = st.columns([2, 1])
    with col_example:
        nl_example = st.selectbox("📋 Quick Examples", list(nl_examples.keys()), key="nl_ex")
    with col_dialect:
        nl_dialect = st.selectbox("🎯 Target Database", DIALECTS, index=1, format_func=get_dialect_label, key="nld")

    default_nl = nl_examples.get(nl_example, "") or "查询所有用户的姓名和邮箱"

    nl_input = st.text_area(
        "Describe your query",
        default_nl,
        height=100,
        key="nl",
        label_visibility="collapsed",
        placeholder="例如: 查询最近7天订单金额大于100的用户 / Get users with orders over $100 in last 7 days"
    )
    
    col_table, col_gen = st.columns([2, 1])
    with col_table:
        nl_table_hint = st.text_input(
            "📋 Table name hint (optional)",
            "",
            key="nl_table",
            placeholder="e.g., users, orders, products"
        )
    with col_gen:
        st.markdown("")
        generate_clicked = st.button("🪄 Generate SQL", type="primary", key="nlbtn", use_container_width=True)

    st.caption("提示：表名、列名等信息可通过“Parsed Elements”区块快速查看，便于后续调整")
    st.markdown('</div>', unsafe_allow_html=True)
    
    if generate_clicked:
        with st.spinner("Generating SQL..."):
            try:
                # Lazy import for performance
                from backend.core.nl2sql import NL2SQLGenerator
                
                gen = NL2SQLGenerator(default_dialect=nl_dialect)
                result = gen.generate(nl_input, dialect=nl_dialect, table_hint=nl_table_hint if nl_table_hint else None)
                
                if result.success and result.sql:
                    st.success("✅ SQL generated successfully!")
                    st.code(result.sql, language="sql")
                    
                    # Confidence and explanation
                    col_conf, col_actions = st.columns([1, 2])
                    with col_conf:
                        conf_color = "🟢" if result.confidence >= 0.7 else "🟡" if result.confidence >= 0.5 else "🔴"
                        st.metric("Confidence", f"{conf_color} {result.confidence:.0%}")
                    with col_actions:
                        col_copy, col_convert = st.columns(2)
                        with col_copy:
                            st.button("📋 Copy", key="nl_copy", use_container_width=True)
                        with col_convert:
                            st.download_button("📥 Download", result.sql, "generated.sql", use_container_width=True)
                    
                    if result.explanation:
                        st.info(f"📝 {result.explanation}")
                    
                    # Parsed elements
                    if result.parsed_elements:
                        with st.expander("🔍 Parsed Elements"):
                            pe = result.parsed_elements
                            cols = st.columns(3)
                            if pe.get("tables"):
                                with cols[0]:
                                    st.markdown("**Tables**")
                                    for t in pe['tables']:
                                        st.code(t)
                            if pe.get("columns"):
                                with cols[1]:
                                    st.markdown("**Columns**")
                                    for c in pe['columns']:
                                        st.code(c)
                            if pe.get("numbers"):
                                with cols[2]:
                                    st.markdown("**Values**")
                                    for n in pe['numbers']:
                                        st.code(n)
                            if pe.get("is_chinese"):
                                st.caption(f"Detected Language: Chinese ({pe.get('token_count')} tokens)")
                else:
                    st.error("❌ Could not generate SQL. Please try phrasing your query differently.")
                    if result.explanation:
                        st.warning(result.explanation)
                        
            except Exception as e:
                st.error(f"Error generating SQL: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
