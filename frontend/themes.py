#!/usr/bin/env python3
"""Theme definitions and CSS generation for SQL Dialect Master UI.

Provides centralized theme management with:
- 5 built-in themes (Dark, Light, Ocean, Sakura, Forest)
- Dynamic CSS generation based on theme
- CSS variable support for consistent styling
- Import/Export functionality for custom themes
"""
from typing import Dict, Any
import json


# =============================================================================
# Theme Definitions
# =============================================================================

THEMES: Dict[str, Dict[str, str]] = {
    "🌙 Dark": {
        "bg": "#0e1117", 
        "fg": "#fafafa", 
        "accent": "#4a9eff", 
        "secondary": "#1e2130", 
        "success": "#00d26a", 
        "warning": "#ffc107", 
        "error": "#ff4b4b", 
        "border": "#333", 
        "card": "#161b22",
        "gradient": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
    },
    "☀️ Light": {
        "bg": "#ffffff", 
        "fg": "#1a1a1a", 
        "accent": "#0066cc", 
        "secondary": "#f8f9fa", 
        "success": "#28a745", 
        "warning": "#fd7e14",
        "error": "#dc3545", 
        "border": "#e1e4e8", 
        "card": "#ffffff",
        "gradient": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
    },
    "🌊 Ocean": {
        "bg": "#0a192f", 
        "fg": "#ccd6f6", 
        "accent": "#64ffda", 
        "secondary": "#112240", 
        "success": "#64ffda", 
        "warning": "#ffd700",
        "error": "#ff6b6b", 
        "border": "#233554", 
        "card": "#0d1f3c",
        "gradient": "linear-gradient(135deg, #0a192f 0%, #112240 100%)"
    },
    "🌸 Sakura": {
        "bg": "#fff5f5", 
        "fg": "#2d3748", 
        "accent": "#ed64a6", 
        "secondary": "#fed7e2", 
        "success": "#48bb78", 
        "warning": "#ed8936",
        "error": "#e53e3e", 
        "border": "#fbb6ce", 
        "card": "#ffffff",
        "gradient": "linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)"
    },
    "🌲 Forest": {
        "bg": "#1a1f16", 
        "fg": "#e8f5e9", 
        "accent": "#81c784", 
        "secondary": "#263238", 
        "success": "#4caf50", 
        "warning": "#ffb74d",
        "error": "#ef5350", 
        "border": "#37474f", 
        "card": "#1e2a1e",
        "gradient": "linear-gradient(135deg, #134e5e 0%, #71b280 100%)"
    }
}

DEFAULT_THEME = "🌊 Ocean"


def get_theme(theme_name: str) -> Dict[str, str]:
    """Get theme by name with fallback to default.
    
    Args:
        theme_name: Theme name (with emoji prefix)
        
    Returns:
        Theme dictionary with color values
    """
    return THEMES.get(theme_name, THEMES[DEFAULT_THEME])


def export_theme_to_json(theme: Dict[str, str]) -> str:
    """Export theme to JSON string.
    
    Args:
        theme: Theme dictionary
        
    Returns:
        Formatted JSON string
    """
    return json.dumps(theme, indent=2)


def import_theme_from_json(json_str: str) -> Dict[str, str]:
    """Import theme from JSON string.
    
    Args:
        json_str: JSON string of theme
    
    Returns:
        Theme dictionary
    
    Raises:
        ValueError: If JSON is invalid or missing keys
    """
    try:
        theme = json.loads(json_str)
        # Validate required keys
        required_keys = ["bg", "fg", "accent", "secondary", "success", "warning", "error", "border", "card", "gradient"]
        missing = [k for k in required_keys if k not in theme]
        if missing:
            raise ValueError(f"Missing required theme keys: {', '.join(missing)}")
        return theme
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {str(e)}")


def generate_theme_css(theme: Dict[str, str]) -> str:
    """Generate complete CSS stylesheet for a theme.
    
    Args:
        theme: Theme dictionary with color values
        
    Returns:
        Complete CSS string for Streamlit HTML injection
    """
    return f"""<style>
/* CSS Variables */
:root {{
    --bg: {theme['bg']};
    --fg: {theme['fg']};
    --accent: {theme['accent']};
    --secondary: {theme['secondary']};
    --success: {theme['success']};
    --warning: {theme['warning']};
    --error: {theme['error']};
    --border: {theme['border']};
    --card: {theme['card']};
}}

/* Main app styling */
.stApp {{
    background: var(--bg);
    color: var(--fg);
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    line-height: 1.6;
}}

/* Global layout helpers */
.page-wrapper {{
    max-width: 1200px;
    margin: 0 auto;
}}

.section-header {{
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    margin: 0.75rem 0 0.5rem;
}}

.section-title {{
    font-weight: 700;
    font-size: 1.1rem;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
}}

.section-subtitle {{
    margin: 0;
    opacity: 0.8;
    font-size: 0.9rem;
}}

.section-kicker {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: {theme['accent']}20;
    color: var(--accent);
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 0.85rem;
}}

.panel {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1rem;
    box-shadow: 0 4px 12px rgba(0,0,0,0.06);
}}

.panel-title {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 700;
    margin-bottom: 0.25rem;
}}

.pill {{
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 6px 12px;
    border-radius: 999px;
    background: var(--secondary);
    border: 1px solid var(--border);
    font-size: 0.85rem;
    color: var(--fg);
}}

/* Hide default Streamlit elements */
#MainMenu {{visibility: hidden;}}
footer {{visibility: hidden;}}
header {{visibility: hidden;}}

/* Custom header */
.main-header {{
    background: {theme['gradient']};
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
    background: linear-gradient(135deg, {theme['accent']}, {theme['accent']}cc);
    color: {theme['bg']};
    border: none;
    border-radius: 10px;
    padding: 0.6rem 1.2rem;
    font-weight: 600;
    font-size: 0.9rem;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 2px 8px {theme['accent']}40;
    text-transform: none;
}}

.stButton>button:hover {{
    transform: translateY(-2px);
    box-shadow: 0 6px 20px {theme['accent']}50;
    filter: brightness(1.1);
}}

.stButton>button:active {{
    transform: translateY(0);
}}

/* Primary button */
.stButton>button[kind="primary"] {{
    background: linear-gradient(135deg, {theme['accent']}, {theme['success']});
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
    background: linear-gradient(135deg, {theme['accent']}, {theme['accent']}cc) !important;
    color: {theme['bg']} !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 0.6rem 1.2rem !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: 0 2px 8px {theme['accent']}40 !important;
    text-transform: none !important;
    width: 100% !important;
}}

.stDownloadButton>button:hover {{
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px {theme['accent']}50 !important;
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
    box-shadow: 0 0 0 3px {theme['accent']}30;
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
    background: {theme['success']}15;
    border-left-color: var(--success);
}}

.stWarning {{
    background: {theme['warning']}15;
    border-left-color: var(--warning);
}}

.stError {{
    background: {theme['error']}15;
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

.badge-success {{ background: {theme['success']}30; color: var(--success); }}
.badge-warning {{ background: {theme['warning']}30; color: var(--warning); }}
.badge-error {{ background: {theme['error']}30; color: var(--error); }}
.badge-info {{ background: {theme['accent']}30; color: var(--accent); }}

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


def generate_keyboard_shortcuts_js() -> str:
    """Generate JavaScript for keyboard shortcuts.
    
    Returns:
        JavaScript code for Streamlit HTML injection
    """
    return """
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
