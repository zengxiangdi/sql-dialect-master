#!/usr/bin/env python3
"""Reusable UI components for SQL Dialect Master Streamlit UI.

Provides helper functions to render common UI elements consistently.
"""
from typing import Dict, Any, Optional
import sys
from pathlib import Path

# Add parent to path for backend imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.config import DIALECT_METADATA, get_dialect_label


def render_dialect_chip(dialect: str, theme: Dict[str, str]) -> str:
    """Render a styled dialect chip/badge.
    
    Args:
        dialect: Dialect identifier
        theme: Current theme dictionary
        
    Returns:
        HTML string for the dialect chip
    """
    info = DIALECT_METADATA.get(dialect)
    if not info:
        return f"<span>{dialect.upper()}</span>"
    
    return f"""
    <div class="dialect-chip" style="background: {theme['secondary']}; border: 1px solid {theme['border']};">
        <span>{info.icon}</span>
        <span style="font-weight: 600;">{dialect.upper()}</span>
    </div>
    """


def render_history_card(
    history_item: Dict[str, str], 
    theme: Dict[str, str],
    preview_length: int = 40
) -> str:
    """Render a history entry card.
    
    Args:
        history_item: Dictionary with 'sql', 'src', 'tgt', 'result' keys
        theme: Current theme dictionary
        preview_length: Maximum characters to show for SQL preview
        
    Returns:
        HTML string for the history card
    """
    src_info = DIALECT_METADATA.get(history_item['src'])
    tgt_info = DIALECT_METADATA.get(history_item['tgt'])
    
    src_icon = src_info.icon if src_info else '📄'
    tgt_icon = tgt_info.icon if tgt_info else '📄'
    
    sql_preview = history_item['sql'][:preview_length]
    if len(history_item['sql']) > preview_length:
        sql_preview += "..."
    
    return f"""
    <div class="card" style="padding: 0.75rem; margin-bottom: 0.5rem;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
            <span>{src_icon}</span>
            <span style="font-weight: 600;">{history_item['src'].upper()}</span>
            <span style="opacity: 0.5;">→</span>
            <span>{tgt_icon}</span>
            <span style="font-weight: 600;">{history_item['tgt'].upper()}</span>
        </div>
        <div style="font-size: 0.8rem; opacity: 0.7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            {sql_preview}
        </div>
    </div>
    """


def render_sql_output(sql: str, theme: Dict[str, str], label: str = "SQL") -> str:
    """Render styled SQL output container.
    
    Args:
        sql: SQL code to display
        theme: Current theme dictionary
        label: Label to show on the container
        
    Returns:
        HTML string for the SQL output container
    """
    return f"""
    <div class="sql-output" style="background: {theme['secondary']}; border: 1px solid {theme['border']};">
        <pre style="margin: 0; white-space: pre-wrap; word-wrap: break-word;">{sql}</pre>
    </div>
    """


def render_main_header(theme: Dict[str, str], subtitle: str = "") -> str:
    """Render the main application header.
    
    Args:
        theme: Current theme dictionary
        subtitle: Subtitle text to display
        
    Returns:
        HTML string for the main header
    """
    if not subtitle:
        subtitle = "Enterprise-grade multi-database SQL conversion platform · 12 Databases · 298 Functions · 36 Types"
    
    return f"""
    <div class="main-header" style="background: {theme['gradient']};">
        <h1>🔄 SQL Dialect Master</h1>
        <p>{subtitle}</p>
    </div>
    """


def render_section_header(title: str, subtitle: str = "", icon: str = "") -> str:
    """Render a compact section header block used across tabs.

    Args:
        title: Main section title text
        subtitle: Supporting caption text
        icon: Optional leading icon

    Returns:
        HTML string for the section header
    """
    icon_html = f"<span class='section-kicker'>{icon}</span>" if icon else ""
    subtitle_html = f"<p class='section-subtitle'>{subtitle}</p>" if subtitle else ""

    return f"""
    <div class="section-header">
        <div class="section-title">{icon_html}{title}</div>
        {subtitle_html}
    </div>
    """


def render_sidebar_branding(theme: Dict[str, str], version: str = "1.0") -> str:
    """Render sidebar branding section.
    
    Args:
        theme: Current theme dictionary
        version: Application version string
        
    Returns:
        HTML string for sidebar branding
    """
    return f"""
    <div style="text-align: center; padding: 1rem 0;">
        <div style="font-size: 3rem; margin-bottom: 0.5rem;">🔄</div>
        <h2 style="margin: 0; color: {theme['accent']};">SQL Dialect Master</h2>
        <p style="opacity: 0.7; font-size: 0.85rem; margin-top: 0.25rem;">v{version} · Enterprise Edition</p>
    </div>
    """


def render_conversion_arrow(theme: Dict[str, str]) -> str:
    """Render the conversion arrow between source and target.
    
    Args:
        theme: Current theme dictionary
        
    Returns:
        HTML string for the arrow
    """
    return f"""
    <div style="text-align: center; padding: 2rem 0;">
        <div style="font-size: 2rem; color: {theme['accent']};">→</div>
    </div>
    """


def render_dialect_grid_item(
    dialect: str, 
    syntax: str, 
    theme: Dict[str, str],
    show_status: bool = False
) -> str:
    """Render a dialect item for grid display.
    
    Args:
        dialect: Dialect identifier
        syntax: Syntax or type to display
        theme: Current theme dictionary
        show_status: Whether to show compatibility status
        
    Returns:
        HTML string for the grid item
    """
    info = DIALECT_METADATA.get(dialect)
    icon = info.icon if info else '📄'
    
    status_html = ""
    if show_status:
        status = "✅" if syntax not in ["N/A", "JSON", "STRING"] else "⚠️"
        status_html = f"<div>{status}</div>"
    
    return f"""
    <div style="background: {theme['secondary']}; padding: 10px; border-radius: 8px; text-align: center;">
        <div style="font-size: 1.2rem;">{icon}</div>
        <div style="font-weight: 600; font-size: 0.85rem;">{dialect.upper()}</div>
        <code style="font-size: 0.75rem;">{syntax}</code>
        {status_html}
    </div>
    """


def render_lineage_result(
    tables: list, 
    output_cols: list, 
    theme: Dict[str, str]
) -> str:
    """Render SQL lineage diagram header.
    
    Args:
        tables: List of source tables
        output_cols: List of output columns
        theme: Current theme dictionary
        
    Returns:
        Mermaid code for the lineage diagram
    """
    mermaid = "```mermaid\nflowchart LR\n"
    mermaid += "    subgraph Sources[\"📥 Source Tables\"]\n"
    for t in tables:
        name = t.get('name', t) if isinstance(t, dict) else t
        mermaid += f"        {name}[(\"{name}\")]\n"
    mermaid += "    end\n\n"
    
    mermaid += "    subgraph Transform[\"⚙️ Transformation\"]\n"
    mermaid += "        QUERY{{\"SQL Query\"}}\n"
    mermaid += "    end\n\n"
    
    mermaid += "    subgraph Output[\"📤 Output\"]\n"
    mermaid += "        RESULT[\"Result Set\"]\n"
    for oc in output_cols[:6]:
        safe_name = str(oc).replace(' ', '_').replace('-', '_')
        mermaid += f"        {safe_name}[\"{oc}\"]\n"
    mermaid += "    end\n\n"
    
    # Edges
    for t in tables:
        name = t.get('name', t) if isinstance(t, dict) else t
        mermaid += f"    {name} --> QUERY\n"
    mermaid += "    QUERY --> RESULT\n"
    for oc in output_cols[:6]:
        safe_name = str(oc).replace(' ', '_').replace('-', '_')
        mermaid += f"    RESULT --> {safe_name}\n"
    
    mermaid += "```"
    return mermaid
