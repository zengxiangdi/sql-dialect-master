#!/usr/bin/env python3
"""Shared application context and utilities for SQL Dialect Master UI.

Contains singleton services, shared constants, and core utility functions
used across multiple UI components.

All SQL conversion goes through the canonical SQLTranspiler to ensure
consistent security validation, stacked-statement detection, and
post-processing behavior.
"""
import streamlit as st
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple

from backend.core.config import SUPPORTED_DIALECTS, get_dialect_ui_info, settings
from backend.core.transpiler import SQLTranspiler

# Singleton transpiler instance for performance and consistency
_transpiler = SQLTranspiler()

# Centralized definitions
DIALECTS = SUPPORTED_DIALECTS
DIALECT_INFO = get_dialect_ui_info()

logger = logging.getLogger(__name__)


@st.cache_data
def load_data() -> Tuple[dict, dict]:
    """Load static data (types, functions) with caching."""
    base = Path(__file__).parent.parent / "backend" / "core"
    types_path = base / "type_mapping.json"
    funcs_path = base / "functions_db.json"

    if not types_path.exists():
        raise FileNotFoundError(f"Missing runtime data file: {types_path}")
    if not funcs_path.exists():
        raise FileNotFoundError(f"Missing runtime data file: {funcs_path}")

    types = json.loads(types_path.read_text(encoding="utf-8"))
    funcs = json.loads(funcs_path.read_text(encoding="utf-8"))
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
    from backend.core.post_processor import PostProcessor
    processor = PostProcessor()
    processed_sql, notes = processor.process(sql, src, tgt)

    # Format notes with icons for UI display
    formatted_notes = []
    for note in notes:
        if note.startswith("WARNING"):
            formatted_notes.append(f"⚠️ {note.replace('WARNING: ', '')}")
        else:
            formatted_notes.append(f"✓ {note}")

    return processed_sql, formatted_notes


def convert(sql: str, src: str, tgt: str) -> Dict[str, Any]:
    """Convert SQL from source to target dialect via the canonical SQLTranspiler.

    Args:
        sql: SQL statement to convert
        src: Source dialect
        tgt: Target dialect

    Returns:
        Dictionary with 'ok', 'sql', 'notes', and optionally 'err'
    """
    try:
        result = _transpiler.transpile(sql, src, tgt, pretty=True)
        if result.success:
            notes = list(result.transformations) + [n for n in result.warnings if n]
            return {"ok": True, "sql": result.target_sql, "notes": notes}
        else:
            logger.debug("Conversion failed: %s", result.error)
            return {"ok": False, "sql": None, "notes": [], "err": result.error or "Conversion failed"}
    except Exception as e:
        logger.debug("Conversion exception: %s", e)
        return {"ok": False, "sql": None, "notes": [], "err": str(e)}


def batch_convert(
    statements: List[str], src: str, tgt: str, pretty: bool = True
) -> List[Dict[str, Any]]:
    """Batch convert multiple SQL statements using the canonical SQLTranspiler.

    Uses the unified batch API to properly handle semicolons in strings,
    comments, and dollar-quoted literals.

    Args:
        statements: List of SQL statements
        src: Source dialect
        tgt: Target dialect
        pretty: Pretty-print output

    Returns:
        List of result dicts with 'ok', 'sql', 'err' keys
    """
    results = _transpiler.batch_transpile(statements, src, tgt, pretty=pretty)
    output = []
    for r in results:
        if r.success:
            output.append({"ok": True, "sql": r.target_sql, "notes": list(r.warnings)})
        else:
            output.append({"ok": False, "sql": None, "err": r.error})
    return output


def format_sql(sql: str, dialect: str) -> str:
    """Format SQL using the canonical transpiler (same dialect round-trip).

    Args:
        sql: SQL to format
        dialect: SQL dialect

    Returns:
        Formatted SQL or original if formatting fails
    """
    try:
        result = _transpiler.transpile(sql, dialect, dialect, pretty=True, validate=False)
        if result.success:
            return result.target_sql
        return sql
    except Exception:
        return sql


def _esc(text: str) -> str:
    """Escape HTML special characters to prevent XSS."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def get_dialect_label(dialect: str) -> str:
    """Get formatted dialect label with icon."""
    info = DIALECT_INFO.get(dialect, {})
    return f"{info.get('icon', '📄')} {dialect.upper()}"
