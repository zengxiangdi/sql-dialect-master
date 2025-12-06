#!/usr/bin/env python3
"""Shared application context and utilities for SQL Dialect Master UI.

Contains singleton services, shared constants, and core utility functions
used across multiple UI components.
"""
import streamlit as st
import sqlglot
import sqlglot.errors
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Setup path and Logger
# Path relative to frontend/app_context.py -> d:/project/frontend/app_context.py
# parent -> d:/project/frontend
# parent.parent -> d:/project
# backend/core -> d:/project/backend/core
BASE = Path(__file__).parent.parent / "backend" / "core"
logger = logging.getLogger(__name__)

from backend.core.post_processor import PostProcessor
from backend.core.config import SUPPORTED_DIALECTS, get_dialect_ui_info

# Singleton PostProcessor instance for performance
_post_processor = PostProcessor()

# Centralized definitions
DIALECTS = SUPPORTED_DIALECTS
DIALECT_INFO = get_dialect_ui_info()

@st.cache_data
def load_data():
    """Load static data (types, functions) with caching."""
    types_path = BASE / "type_mapping.json"
    funcs_path = BASE / "functions_db.json"
    
    types = json.loads(types_path.read_text(encoding='utf-8')) if types_path.exists() else {"mappings": {}}
    funcs = json.loads(funcs_path.read_text(encoding='utf-8')) if funcs_path.exists() else {"functions": []}
    return types, funcs

def post_process(sql: str, src: str, tgt: str) -> Tuple[str, List[str]]:
    """Apply post-processing rules using the singleton PostProcessor.
    
    Delegates to backend.core.post_processor.PostProcessor.
    
    Args:
        sql: SQL to process
        src: Source dialect
        tgt: Target dialect
        
    Returns:
        Tuple of (processed_sql, formatted_notes)
    """
    processed_sql, notes = _post_processor.process(sql, src, tgt)
    
    # Format notes with icons for UI display
    formatted_notes = []
    for note in notes:
        if note.startswith("WARNING"):
            formatted_notes.append(f"⚠️ {note.replace('WARNING: ', '')}")
        else:
            formatted_notes.append(f"✓ {note}")
    
    return processed_sql, formatted_notes

def convert(sql: str, src: str, tgt: str) -> Dict[str, Any]:
    """Convert SQL from source to target dialect.
    
    Args:
        sql: SQL statement to convert
        src: Source dialect
        tgt: Target dialect
        
    Returns:
        Dictionary with 'ok', 'sql', 'notes', and optionally 'err'
    """
    try:
        out = sqlglot.transpile(sql, read=src, write=tgt, pretty=True)[0]
        out, notes = post_process(out, src, tgt)
        return {"ok": True, "sql": out, "notes": notes}
    except Exception as e:
        logger.debug(f"Conversion failed: {e}")
        return {"ok": False, "sql": None, "notes": [], "err": str(e)}

def format_sql(sql: str, dialect: str) -> str:
    """Format SQL using sqlglot.
    
    Args:
        sql: SQL to format
        dialect: SQL dialect
        
    Returns:
        Formatted SQL or original if formatting fails
    """
    try:
        return sqlglot.transpile(sql, read=dialect, write=dialect, pretty=True)[0]
    except (sqlglot.errors.ParseError, Exception) as e:
        logger.debug(f"SQL formatting failed: {e}")
        return sql

def get_dialect_label(dialect: str) -> str:
    """Get formatted dialect label with icon."""
    info = DIALECT_INFO.get(dialect, {})
    return f"{info.get('icon', '📄')} {dialect.upper()}"
