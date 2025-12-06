#!/usr/bin/env python3
"""SQL Dialect Master - Local Streamlit Version
Run: pip install sqlglot streamlit && streamlit run sdm_local.py
"""
import streamlit as st
import sqlglot
import json, re, difflib
from pathlib import Path
from datetime import datetime

DIALECTS = ["hive", "mysql", "oracle", "tsql", "postgres", "spark", "trino", "snowflake", "redshift", "clickhouse", "duckdb", "databricks"]
BASE = Path(__file__).parent / "backend" / "core"

# Dialect display info with icons
DIALECT_INFO = {
    "hive": {"icon": "🐝", "name": "Apache Hive", "color": "#FDEE21"},
    "mysql": {"icon": "🐬", "name": "MySQL", "color": "#00758F"},
    "oracle": {"icon": "🔴", "name": "Oracle", "color": "#F80000"},
    "tsql": {"icon": "🟦", "name": "SQL Server", "color": "#CC2927"},
    "postgres": {"icon": "🐘", "name": "PostgreSQL", "color": "#336791"},
    "spark": {"icon": "⚡", "name": "Spark SQL", "color": "#E25A1C"},
    "trino": {"icon": "🔷", "name": "Trino", "color": "#DD00A1"},
    "snowflake": {"icon": "❄️", "name": "Snowflake", "color": "#29B5E8"},
    "redshift": {"icon": "🔶", "name": "Redshift", "color": "#8C4FFF"},
    "clickhouse": {"icon": "🏠", "name": "ClickHouse", "color": "#FFCC00"},
    "duckdb": {"icon": "🦆", "name": "DuckDB", "color": "#FFF000"},
    "databricks": {"icon": "🧱", "name": "Databricks", "color": "#FF3621"}
}

# Common SQL templates (30+ templates)
TEMPLATES = {
    "-- Select a template --": "",
    # Basic queries
    "📅 Last 7 days data": "SELECT * FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)",
    "🔝 Top 100 with LIMIT": "SELECT * FROM users ORDER BY score DESC LIMIT 100",
    "🎲 DISTINCT with ORDER": "SELECT DISTINCT category, brand FROM products ORDER BY category, brand",
    "🔄 COALESCE null handling": "SELECT id, COALESCE(nickname, username, email, 'Anonymous') AS display_name FROM users",
    # Window functions
    "📊 Window ROW_NUMBER": "SELECT *, ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) AS rn FROM employees",
    "📊 Window LAG/LEAD": "SELECT date, amount, LAG(amount, 1, 0) OVER (ORDER BY date) AS prev_amount, LEAD(amount, 1, 0) OVER (ORDER BY date) AS next_amount FROM sales",
    "📊 Window RANK/DENSE_RANK": "SELECT name, score, RANK() OVER (ORDER BY score DESC) AS rank, DENSE_RANK() OVER (ORDER BY score DESC) AS dense_rank FROM students",
    "📊 Window NTILE": "SELECT name, salary, NTILE(4) OVER (ORDER BY salary DESC) AS quartile FROM employees",
    "📊 Window Running Total": "SELECT date, amount, SUM(amount) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING) AS running_total FROM sales",
    # JSON operations
    "🔗 JSON nested parse": "SELECT id, GET_JSON_OBJECT(data, '$.items[0].name') AS first_item FROM events",
    "🔗 JSON array extract": "SELECT id, JSON_EXTRACT(metadata, '$.tags') AS tags FROM products",
    "🔗 JSON object build": "SELECT id, JSON_OBJECT('name', name, 'email', email) AS user_json FROM users",
    # Array operations
    "📦 Array explode": "SELECT id, tag FROM products LATERAL VIEW EXPLODE(tags) t AS tag",
    "📦 Array aggregate": "SELECT user_id, COLLECT_LIST(product_id) AS purchased_products FROM orders GROUP BY user_id",
    "📦 Array contains": "SELECT * FROM products WHERE ARRAY_CONTAINS(tags, 'sale')",
    # Aggregations
    "📈 Group aggregation": "SELECT dept, COUNT(*) AS cnt, AVG(salary) AS avg_sal FROM employees GROUP BY dept",
    "📈 HAVING filter": "SELECT dept, COUNT(*) AS emp_count FROM employees GROUP BY dept HAVING COUNT(*) > 5 ORDER BY emp_count DESC",
    "🔄 String aggregation": "SELECT dept, COLLECT_LIST(name) AS names FROM employees GROUP BY dept",
    "📈 Multiple aggregates": "SELECT category, COUNT(*) AS cnt, SUM(price) AS total, AVG(price) AS avg_price, MAX(price) AS max_price FROM products GROUP BY category",
    # Joins
    "🔗 Multi-table JOIN": "SELECT u.name, o.order_id, p.product_name FROM users u JOIN orders o ON u.id = o.user_id JOIN products p ON o.product_id = p.id",
    "🔗 LEFT JOIN with NULL": "SELECT u.name, COUNT(o.id) AS order_count FROM users u LEFT JOIN orders o ON u.id = o.user_id GROUP BY u.name",
    "🔗 Self JOIN": "SELECT e.name AS employee, m.name AS manager FROM employees e LEFT JOIN employees m ON e.manager_id = m.id",
    "🔗 CROSS JOIN": "SELECT p.name, c.color FROM products p CROSS JOIN colors c",
    # Subqueries
    "📉 Subquery IN clause": "SELECT * FROM products WHERE category_id IN (SELECT id FROM categories WHERE status = 'active')",
    "📉 Correlated subquery": "SELECT * FROM employees e WHERE salary > (SELECT AVG(salary) FROM employees WHERE dept = e.dept)",
    "📉 EXISTS subquery": "SELECT * FROM customers c WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id AND o.amount > 1000)",
    # CTEs
    "🔀 CTE basic": "WITH active_users AS (SELECT * FROM users WHERE status = 'active') SELECT * FROM active_users WHERE created_at > '2024-01-01'",
    "🔀 CTE recursive": "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n+1 FROM cte WHERE n < 10) SELECT * FROM cte",
    "🔀 CTE multiple": "WITH sales_2024 AS (SELECT * FROM sales WHERE YEAR(date) = 2024), top_products AS (SELECT product_id, SUM(amount) AS total FROM sales_2024 GROUP BY product_id) SELECT * FROM top_products ORDER BY total DESC LIMIT 10",
    # Date operations
    "📅 Date extraction": "SELECT YEAR(created_at) AS year, MONTH(created_at) AS month, COUNT(*) AS cnt FROM orders GROUP BY YEAR(created_at), MONTH(created_at)",
    "📅 Date range filter": "SELECT * FROM logs WHERE log_time BETWEEN '2024-01-01' AND '2024-12-31'",
    "📅 Date arithmetic": "SELECT id, created_at, DATE_ADD(created_at, 30) AS expires_at FROM subscriptions",
    "📅 Date formatting": "SELECT id, DATE_FORMAT(created_at, '%Y-%m-%d') AS formatted_date FROM orders",
    # CASE expressions
    "🎯 CASE WHEN": "SELECT id, name, CASE WHEN score >= 90 THEN 'A' WHEN score >= 80 THEN 'B' WHEN score >= 60 THEN 'C' ELSE 'F' END AS grade FROM students",
    "🎯 CASE with aggregation": "SELECT SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed, SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending FROM orders",
    # Set operations
    "🔢 UNION ALL": "SELECT 'Q1' AS quarter, SUM(amount) AS total FROM sales WHERE month <= 3 UNION ALL SELECT 'Q2', SUM(amount) FROM sales WHERE month BETWEEN 4 AND 6",
    "🔢 INTERSECT": "SELECT user_id FROM orders WHERE YEAR(created_at) = 2023 INTERSECT SELECT user_id FROM orders WHERE YEAR(created_at) = 2024",
    "🔢 EXCEPT": "SELECT user_id FROM users EXCEPT SELECT DISTINCT user_id FROM orders",
    # Advanced
    "🚀 Pivot simulation": "SELECT product_id, SUM(CASE WHEN month = 1 THEN amount END) AS jan, SUM(CASE WHEN month = 2 THEN amount END) AS feb, SUM(CASE WHEN month = 3 THEN amount END) AS mar FROM sales GROUP BY product_id",
    "🚀 Percentile": "SELECT dept, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary) AS median_salary FROM employees GROUP BY dept",
    "🚀 Cumulative distribution": "SELECT name, salary, CUME_DIST() OVER (ORDER BY salary) AS percentile FROM employees"
}

@st.cache_data
def load_data():
    types = json.loads((BASE / "type_mapping.json").read_text()) if (BASE / "type_mapping.json").exists() else {"mappings": {}}
    funcs = json.loads((BASE / "functions_db.json").read_text()) if (BASE / "functions_db.json").exists() else {"functions": []}
    return types, funcs

def post_process(sql, src, tgt):
    """Apply post-processing rules using the centralized PostProcessor.
    
    This function delegates to backend.core.post_processor.PostProcessor
    to ensure consistent behavior across all entry points (API, CLI, Streamlit).
    """
    import sys
    sys.path.insert(0, str(BASE.parent.parent))
    
    from backend.core.post_processor import PostProcessor
    
    pp = PostProcessor()
    processed_sql, notes = pp.process(sql, src, tgt)
    
    # Format notes with icons for UI display
    formatted_notes = []
    for note in notes:
        if note.startswith("WARNING"):
            formatted_notes.append(f"⚠️ {note.replace('WARNING: ', '')}")
        else:
            formatted_notes.append(f"✓ {note}")
    
    return processed_sql, formatted_notes

def convert(sql, src, tgt):
    try:
        out = sqlglot.transpile(sql, read=src, write=tgt, pretty=True)[0]
        out, notes = post_process(out, src, tgt)
        return {"ok": True, "sql": out, "notes": notes}
    except Exception as e:
        return {"ok": False, "sql": None, "notes": [], "err": str(e)}

def format_sql(sql, dialect):
    try:
        return sqlglot.transpile(sql, read=dialect, write=dialect, pretty=True)[0]
    except:
        return sql

def get_dialect_label(dialect):
    """Get formatted dialect label with icon."""
    info = DIALECT_INFO.get(dialect, {})
    return f"{info.get('icon', '📄')} {dialect.upper()}"

# === STREAMLIT APP ===
st.set_page_config(
    page_title="SQL Dialect Master", 
    page_icon="🔄",
    layout="wide", 
    initial_sidebar_state="expanded"
)

# Initialize session state
defaults = {
    "theme": "🌊 Ocean",
    "dark_mode": True,
    "history": [],
    "favorites": [],
    "load_sql": None,
    "last_conversion": None,
    "show_welcome": True
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Enhanced theme definitions
THEMES = {
    "🌙 Dark": {
        "bg": "#0e1117", "fg": "#fafafa", "accent": "#4a9eff", 
        "secondary": "#1e2130", "success": "#00d26a", "warning": "#ffc107", 
        "error": "#ff4b4b", "border": "#333", "card": "#161b22",
        "gradient": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
    },
    "☀️ Light": {
        "bg": "#ffffff", "fg": "#1a1a1a", "accent": "#0066cc", 
        "secondary": "#f8f9fa", "success": "#28a745", "warning": "#fd7e14",
        "error": "#dc3545", "border": "#e1e4e8", "card": "#ffffff",
        "gradient": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
    },
    "🌊 Ocean": {
        "bg": "#0a192f", "fg": "#ccd6f6", "accent": "#64ffda", 
        "secondary": "#112240", "success": "#64ffda", "warning": "#ffd700",
        "error": "#ff6b6b", "border": "#233554", "card": "#0d1f3c",
        "gradient": "linear-gradient(135deg, #0a192f 0%, #112240 100%)"
    },
    "🌸 Sakura": {
        "bg": "#fff5f5", "fg": "#2d3748", "accent": "#ed64a6", 
        "secondary": "#fed7e2", "success": "#48bb78", "warning": "#ed8936",
        "error": "#e53e3e", "border": "#fbb6ce", "card": "#ffffff",
        "gradient": "linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)"
    },
    "🌲 Forest": {
        "bg": "#1a1f16", "fg": "#e8f5e9", "accent": "#81c784", 
        "secondary": "#263238", "success": "#4caf50", "warning": "#ffb74d",
        "error": "#ef5350", "border": "#37474f", "card": "#1e2a1e",
        "gradient": "linear-gradient(135deg, #134e5e 0%, #71b280 100%)"
    }
}

current_theme = THEMES.get(st.session_state.theme, THEMES["🌊 Ocean"])

# Enhanced CSS with modern design
theme_css = f"""<style>
/* CSS Variables */
:root {{
    --bg: {current_theme['bg']};
    --fg: {current_theme['fg']};
    --accent: {current_theme['accent']};
    --secondary: {current_theme['secondary']};
    --success: {current_theme['success']};
    --warning: {current_theme['warning']};
    --error: {current_theme['error']};
    --border: {current_theme['border']};
    --card: {current_theme['card']};
}}

/* Main app styling */
.stApp {{
    background: var(--bg);
    color: var(--fg);
}}

/* Hide default Streamlit elements */
#MainMenu {{visibility: hidden;}}
footer {{visibility: hidden;}}
header {{visibility: hidden;}}

/* Custom header */
.main-header {{
    background: {current_theme['gradient']};
    padding: 1.5rem 2rem;
    border-radius: 16px;
    margin-bottom: 1.5rem;
    box-shadow: 0 4px 20px rgba(0,0,0,0.15);
}}

.main-header h1 {{
    margin: 0;
    font-size: 2rem;
    font-weight: 700;
    color: white;
    text-shadow: 0 2px 4px rgba(0,0,0,0.2);
}}

.main-header p {{
    margin: 0.5rem 0 0 0;
    opacity: 0.9;
    color: white;
}}

/* Card styling */
.card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem;
    margin-bottom: 1rem;
    transition: all 0.3s ease;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}}

.card:hover {{
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
    border-color: var(--accent);
}}

/* Button styling */
.stButton>button {{
    background: linear-gradient(135deg, {current_theme['accent']}, {current_theme['accent']}cc);
    color: {current_theme['bg']};
    border: none;
    border-radius: 10px;
    padding: 0.6rem 1.2rem;
    font-weight: 600;
    font-size: 0.9rem;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 2px 8px {current_theme['accent']}40;
    text-transform: none;
}}

.stButton>button:hover {{
    transform: translateY(-2px);
    box-shadow: 0 6px 20px {current_theme['accent']}50;
    filter: brightness(1.1);
}}

.stButton>button:active {{
    transform: translateY(0);
}}

/* Primary button */
.stButton>button[kind="primary"] {{
    background: linear-gradient(135deg, {current_theme['accent']}, {current_theme['success']});
    font-size: 1rem;
    padding: 0.75rem 1.5rem;
}}

/* Secondary/outline buttons */
.stButton>button[kind="secondary"] {{
    background: transparent;
    border: 2px solid var(--accent);
    color: var(--accent);
}}

/* Download button styling - match regular buttons */
.stDownloadButton>button {{
    background: linear-gradient(135deg, {current_theme['accent']}, {current_theme['accent']}cc) !important;
    color: {current_theme['bg']} !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 0.6rem 1.2rem !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: 0 2px 8px {current_theme['accent']}40 !important;
    text-transform: none !important;
    width: 100% !important;
}}

.stDownloadButton>button:hover {{
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px {current_theme['accent']}50 !important;
    filter: brightness(1.1) !important;
}}

.stDownloadButton>button:active {{
    transform: translateY(0) !important;
}}

/* Expander styling */
.stExpander {{
    background: var(--secondary);
    border-radius: 12px;
    border: 1px solid var(--border);
    overflow: hidden;
}}

.stExpander > div:first-child {{
    border-radius: 12px 12px 0 0;
}}

/* Code block styling */
.stCodeBlock {{
    border-radius: 10px;
    border: 1px solid var(--border);
}}

pre {{
    background: var(--secondary) !important;
    border-radius: 10px;
    padding: 1rem !important;
}}

code {{
    background: var(--secondary);
    border-radius: 6px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
}}

/* Tab styling */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background: var(--secondary);
    border-radius: 12px;
    padding: 6px;
}}

.stTabs [data-baseweb="tab"] {{
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: 500;
    color: var(--fg);
    background: transparent;
    transition: all 0.2s ease;
}}

.stTabs [data-baseweb="tab"]:hover {{
    background: var(--border);
}}

.stTabs [aria-selected="true"] {{
    background: var(--accent) !important;
    color: var(--bg) !important;
}}

/* Input fields */
.stTextInput>div>div>input, 
.stTextArea>div>div>textarea {{
    border-radius: 10px;
    border: 2px solid var(--border);
    background: var(--secondary);
    color: var(--fg);
    padding: 0.75rem 1rem;
    transition: all 0.2s ease;
}}

.stTextInput>div>div>input:focus, 
.stTextArea>div>div>textarea:focus {{
    border-color: var(--accent);
    box-shadow: 0 0 0 3px {current_theme['accent']}30;
}}

/* Selectbox */
.stSelectbox>div>div {{
    border-radius: 10px;
    border: 2px solid var(--border);
    background: var(--secondary);
}}

.stSelectbox>div>div:hover {{
    border-color: var(--accent);
}}

/* Metric styling */
[data-testid="stMetricValue"] {{
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--accent);
}}

[data-testid="stMetricLabel"] {{
    font-size: 0.85rem;
    color: var(--fg);
    opacity: 0.8;
}}

/* Sidebar styling */
[data-testid="stSidebar"] {{
    background: var(--secondary);
    border-right: 1px solid var(--border);
}}

[data-testid="stSidebar"] .stButton>button {{
    width: 100%;
}}

/* Dataframe styling */
.stDataFrame {{
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--border);
}}

/* Alert/Message styling */
.stSuccess, .stInfo, .stWarning, .stError {{
    border-radius: 10px;
    padding: 1rem;
    border-left-width: 4px;
}}

.stSuccess {{
    background: {current_theme['success']}15;
    border-left-color: var(--success);
}}

.stWarning {{
    background: {current_theme['warning']}15;
    border-left-color: var(--warning);
}}

.stError {{
    background: {current_theme['error']}15;
    border-left-color: var(--error);
}}

/* Custom scrollbar */
::-webkit-scrollbar {{
    width: 8px;
    height: 8px;
}}

::-webkit-scrollbar-track {{
    background: var(--secondary);
    border-radius: 4px;
}}

::-webkit-scrollbar-thumb {{
    background: var(--accent);
    border-radius: 4px;
    opacity: 0.6;
}}

::-webkit-scrollbar-thumb:hover {{
    opacity: 1;
}}

/* Animations */
@keyframes fadeIn {{
    from {{ opacity: 0; transform: translateY(10px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}

@keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.6; }}
}}

@keyframes slideIn {{
    from {{ transform: translateX(-20px); opacity: 0; }}
    to {{ transform: translateX(0); opacity: 1; }}
}}

.animate-fade {{ animation: fadeIn 0.4s ease-out; }}
.animate-pulse {{ animation: pulse 2s infinite; }}
.animate-slide {{ animation: slideIn 0.3s ease-out; }}

/* Status badges */
.badge {{
    display: inline-block;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
}}

.badge-success {{ background: {current_theme['success']}30; color: var(--success); }}
.badge-warning {{ background: {current_theme['warning']}30; color: var(--warning); }}
.badge-error {{ background: {current_theme['error']}30; color: var(--error); }}
.badge-info {{ background: {current_theme['accent']}30; color: var(--accent); }}

/* Tooltip styling */
[data-tooltip] {{
    position: relative;
    cursor: help;
}}

/* Progress indicator */
.progress-bar {{
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
}}

.progress-bar-fill {{
    height: 100%;
    background: linear-gradient(90deg, var(--accent), var(--success));
    border-radius: 2px;
    transition: width 0.3s ease;
}}

/* Dialect chip */
.dialect-chip {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: var(--secondary);
    border: 1px solid var(--border);
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 500;
    transition: all 0.2s ease;
}}

.dialect-chip:hover {{
    border-color: var(--accent);
    background: var(--accent)15;
}}

/* SQL code highlight */
.sql-output {{
    background: var(--secondary);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1rem;
    font-family: 'JetBrains Mono', monospace;
    position: relative;
}}

.sql-output::before {{
    content: 'SQL';
    position: absolute;
    top: -10px;
    left: 12px;
    background: var(--accent);
    color: var(--bg);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
}}

/* Responsive grid */
.grid-2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; }}
.grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }}
.grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; }}

@media (max-width: 768px) {{
    .grid-2, .grid-3, .grid-4 {{ grid-template-columns: 1fr; }}
}}

/* Floating action button */
.fab {{
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: var(--accent);
    color: var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5rem;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    cursor: pointer;
    transition: all 0.3s ease;
    z-index: 1000;
}}

.fab:hover {{
    transform: scale(1.1);
    box-shadow: 0 6px 20px rgba(0,0,0,0.4);
}}
</style>"""
st.markdown(theme_css, unsafe_allow_html=True)

# Keyboard shortcuts
shortcuts_js = """
<script>
document.addEventListener('keydown', function(e) {
    if (e.ctrlKey && e.key === 'Enter') {
        e.preventDefault();
        const convertBtn = document.querySelector('button[kind="primary"]');
        if (convertBtn) convertBtn.click();
    }
    if (e.ctrlKey && e.shiftKey && e.key === 'F') {
        e.preventDefault();
        const formatBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Format'));
        if (formatBtn) formatBtn.click();
    }
    if (e.key === 'F11') {
        e.preventDefault();
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen();
        } else {
            document.exitFullscreen();
        }
    }
});
</script>
"""
st.markdown(shortcuts_js, unsafe_allow_html=True)

types_data, funcs_data = load_data()

# === SIDEBAR ===
with st.sidebar:
    # Logo and branding
    st.markdown(f"""
    <div style="text-align: center; padding: 1rem 0;">
        <div style="font-size: 3rem; margin-bottom: 0.5rem;">🔄</div>
        <h2 style="margin: 0; color: {current_theme['accent']};">SQL Dialect Master</h2>
        <p style="opacity: 0.7; font-size: 0.85rem; margin-top: 0.25rem;">v1.0 · Enterprise Edition</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Theme selector with preview
    st.markdown("#### 🎨 Theme")
    new_theme = st.selectbox(
        "Select theme",
        list(THEMES.keys()), 
        index=list(THEMES.keys()).index(st.session_state.theme),
        key="theme_sel",
        label_visibility="collapsed"
    )
    if new_theme != st.session_state.theme:
        st.session_state.theme = new_theme
        st.rerun()
    
    # Quick stats
    st.markdown("---")
    st.markdown("#### 📊 Session Stats")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.metric("Conversions", len(st.session_state.history), help="Total conversions this session")
    with col_s2:
        st.metric("Favorites", len(st.session_state.favorites), help="Saved favorite queries")
    
    # History section
    st.markdown("---")
    st.markdown("#### 📜 Recent History")
    
    if st.session_state.history:
        for i, h in enumerate(st.session_state.history[-5:][::-1]):
            src_info = DIALECT_INFO.get(h['src'], {})
            tgt_info = DIALECT_INFO.get(h['tgt'], {})
            
            with st.container():
                st.markdown(f"""
                <div class="card" style="padding: 0.75rem; margin-bottom: 0.5rem;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                        <span>{src_info.get('icon', '📄')}</span>
                        <span style="font-weight: 600;">{h['src'].upper()}</span>
                        <span style="opacity: 0.5;">→</span>
                        <span>{tgt_info.get('icon', '📄')}</span>
                        <span style="font-weight: 600;">{h['tgt'].upper()}</span>
                    </div>
                    <div style="font-size: 0.8rem; opacity: 0.7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        {h['sql'][:40]}...
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                col_load, col_fav = st.columns(2)
                with col_load:
                    if st.button("📂 Load", key=f"hist_{i}", use_container_width=True):
                        st.session_state.load_sql = h
                        st.rerun()
                with col_fav:
                    if st.button("⭐ Save", key=f"fav_{i}", use_container_width=True):
                        if h not in st.session_state.favorites:
                            st.session_state.favorites.append(h)
                            st.toast("⭐ Added to favorites!")
        
        if st.button("🗑️ Clear History", key="clear_hist", use_container_width=True):
            st.session_state.history = []
            st.rerun()
    else:
        st.info("No conversions yet. Start converting!")
    
    # Favorites section
    st.markdown("---")
    st.markdown("#### ⭐ Favorites")
    
    if st.session_state.favorites:
        for i, f in enumerate(st.session_state.favorites[:5]):
            src_info = DIALECT_INFO.get(f['src'], {})
            tgt_info = DIALECT_INFO.get(f['tgt'], {})
            
            col_f, col_rm = st.columns([4, 1])
            with col_f:
                label = f['sql'][:25] + "..." if len(f['sql']) > 25 else f['sql']
                if st.button(f"{src_info.get('icon', '')} → {tgt_info.get('icon', '')} {label}", key=f"favload_{i}", use_container_width=True):
                    st.session_state.load_sql = f
                    st.rerun()
            with col_rm:
                if st.button("✕", key=f"rmfav_{i}"):
                    st.session_state.favorites.remove(f)
                    st.rerun()
        
        all_favs = "\n\n".join([f"-- {f['src']} → {f['tgt']}\n{f['result']}" for f in st.session_state.favorites])
        st.download_button("📥 Export All", all_favs, "favorites.sql", use_container_width=True)
    else:
        st.info("Star your favorite queries!")
    
    # Keyboard shortcuts
    st.markdown("---")
    st.markdown("#### ⌨️ Shortcuts")
    st.caption("`Ctrl+Enter` Convert")
    st.caption("`Ctrl+Shift+F` Format")
    st.caption("`F11` Fullscreen")

# === MAIN CONTENT ===
# Header
st.markdown(f"""
<div class="main-header">
    <h1>🔄 SQL Dialect Master</h1>
    <p>Enterprise-grade multi-database SQL conversion platform · 12 Databases · 298 Functions · 36 Types</p>
</div>
""", unsafe_allow_html=True)

# Quick stats bar
stat_cols = st.columns(4)
with stat_cols[0]:
    st.metric("📚 Functions", "298", help="SQL functions in encyclopedia")
with stat_cols[1]:
    st.metric("🗂️ Types", "36", help="Data types mapped")
with stat_cols[2]:
    st.metric("🔧 Rules", "40", help="Conversion rules")
with stat_cols[3]:
    st.metric("💾 Databases", "12", help="Supported databases")

st.markdown("")

# Main tabs with icons
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚡ Convert", 
    "📚 Functions", 
    "🗂️ Types", 
    "💬 NL2SQL", 
    "📊 Explain", 
    "🔗 Lineage"
])

# === TAB 1: SQL CONVERT ===
with tab1:
    # Template selector with better UX
    st.markdown("#### 📋 Quick Start")
    template_choice = st.selectbox(
        "Choose a template or write your own SQL",
        list(TEMPLATES.keys()), 
        key="tpl",
        label_visibility="collapsed"
    )
    default_sql = TEMPLATES.get(template_choice, "") or "SELECT * FROM users WHERE id = 1"
    
    # Load from history/favorites
    if st.session_state.load_sql:
        loaded = st.session_state.load_sql
        default_sql = loaded["sql"]
        st.session_state.load_sql = None
    
    # Main conversion area
    col_src, col_arrow, col_tgt = st.columns([5, 1, 5])
    
    with col_src:
        st.markdown("##### Source")
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
        st.markdown("##### Target")
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
                if hist_entry not in st.session_state.history:
                    st.session_state.history.append(hist_entry)
                
                # Success message
                st.success("✅ Conversion successful!")
                
                # Output SQL
                st.code(r["sql"], language="sql")
                
                # Action buttons
                col_copy, col_dl, col_fav = st.columns(3)
                with col_copy:
                    st.button("📋 Copy", key="copy_btn", use_container_width=True)
                    st.markdown(f'<textarea id="sql_copy" style="position:absolute;left:-9999px">{r["sql"]}</textarea><script>navigator.clipboard.writeText(document.getElementById("sql_copy").value)</script>', unsafe_allow_html=True)
                with col_dl:
                    st.download_button("📥 Download", r["sql"], "converted.sql", use_container_width=True)
                with col_fav:
                    if st.button("⭐ Favorite", key="fav_result", use_container_width=True):
                        if hist_entry not in st.session_state.favorites:
                            st.session_state.favorites.append(hist_entry)
                            st.toast("⭐ Added to favorites!")
                
                # Transformation notes
                if r["notes"]:
                    st.markdown("##### 🔧 Transformations Applied")
                    for n in r["notes"]:
                        st.info(n)
            else:
                st.error(f"❌ Conversion failed: {r['err']}")
    
    # Detailed analysis section
    if st.session_state.get("last_conversion"):
        r = st.session_state["last_conversion"]
        
        st.markdown("---")
        st.markdown("#### 📊 Conversion Analysis")
        
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

# === TAB 2: FUNCTION ENCYCLOPEDIA ===
with tab2:
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

# === TAB 3: TYPE MAPPING ===
with tab3:
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

# === TAB 4: NL2SQL ===
with tab4:
    st.markdown("#### 💬 Natural Language → SQL")
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
    
    if generate_clicked:
        with st.spinner("Generating SQL..."):
            try:
                import sys
                sys.path.insert(0, str(BASE.parent.parent))
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
                    
                    if result.suggestions:
                        st.markdown("##### 💡 Suggestions")
                        for sug in result.suggestions:
                            st.warning(sug)
                else:
                    st.error("❌ Could not parse input. Please try a more specific description.")
            except Exception as e:
                st.error(f"❌ Generation failed: {e}")
                # Fallback
                kw = nl_input.lower()
                if any(w in kw for w in ["查询", "select", "获取", "get", "find"]):
                    sql = f"SELECT * FROM table_name WHERE condition"
                elif any(w in kw for w in ["插入", "insert", "添加", "add"]):
                    sql = f"INSERT INTO table_name (col1, col2) VALUES (val1, val2)"
                elif any(w in kw for w in ["更新", "update", "修改"]):
                    sql = f"UPDATE table_name SET col = value WHERE condition"
                elif any(w in kw for w in ["删除", "delete", "移除"]):
                    sql = f"DELETE FROM table_name WHERE condition"
                else:
                    sql = f"-- Could not parse: {nl_input}"
                st.code(sql, language="sql")
    
    # Usage tips
    with st.expander("📖 Usage Tips"):
        col_tips1, col_tips2 = st.columns(2)
        with col_tips1:
            st.markdown("""
**Supported Tables:**
- 用户/users, 订单/orders
- 产品/products, 员工/employees
- 部门/departments, 客户/customers
- 日志/logs, 交易/transactions

**Supported Columns:**
- 姓名/name, 邮箱/email
- 年龄/age, 金额/amount
- 价格/price, 状态/status
            """)
        with col_tips2:
            st.markdown("""
**Supported Operations:**
- 聚合: count, sum, avg, max, min
- 条件: >, <, =, like, is null
- 时间: today, yesterday, last N days
- 排序: asc, desc
- 分组: group by
- 限制: top N, limit
            """)

# === TAB 5: EXPLAIN COMPARE ===
with tab5:
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

# === TAB 6: SQL LINEAGE ===
with tab6:
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

# Footer
st.markdown("---")
st.markdown(f"""
<div style="text-align: center; padding: 1rem; opacity: 0.7;">
    <p>SQL Dialect Master v1.0 · Built with ❤️ using Streamlit & sqlglot</p>
    <p style="font-size: 0.8rem;">Supports 12 databases · 298 functions · 36 data types · 40 conversion rules</p>
</div>
""", unsafe_allow_html=True)
