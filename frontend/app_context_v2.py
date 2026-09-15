"""App context for SQL Dialect Master v2 — the thin adapter layer between
frontend and backend that returns typed ViewModels instead of raw dicts.

All SQL conversion goes through the canonical SQLTranspiler to ensure
consistent security validation, stacked-statement detection, and
post-processing behavior.
"""
from __future__ import annotations

import logging

import streamlit as st

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_legacy import NL2SQLResult
from backend.core.transpiler import SQLTranspiler, TranspileResult

logger = logging.getLogger(__name__)

# Singleton transpiler instance
_transpiler = SQLTranspiler()


def convert_sql(sql: str, src: str, tgt: str) -> TranspileResult:
    """Convert SQL through the canonical SQLTranspiler.

    Args:
        sql: SQL statement to convert
        src: Source dialect
        tgt: Target dialect

    Returns:
        TranspileResult from the backend
    """
    return _transpiler.transpile(sql, src, tgt, pretty=True)


def batch_convert_sql(
    statements: list[str], src: str, tgt: str, pretty: bool = True
) -> list[TranspileResult]:
    """Batch convert multiple SQL statements.

    Uses the canonical batch API which properly handles semicolons in
    strings, comments, and dollar-quoted literals.

    Args:
        statements: List of SQL statement strings
        src: Source dialect
        tgt: Target dialect
        pretty: Pretty-print output

    Returns:
        List of TranspileResult objects
    """
    return _transpiler.batch_transpile(statements, src, tgt, pretty=pretty)


def format_sql_local(sql: str, dialect: str) -> str:
    """Format SQL by round-tripping through the transpiler.

    Args:
        sql: SQL to format
        dialect: SQL dialect

    Returns:
        Formatted SQL or original if formatting fails
    """
    try:
        result = _transpiler.transpile(sql, dialect, dialect, pretty=True, validate=False)
        if result.success:
            return result.target_sql or sql
        return sql
    except Exception:  # noqa: BLE001 — transpiler already handles errors; this is a fallback
        return sql


def generate_nl2sql(nl: str, dialect: str, table_hint: str | None = None) -> NL2SQLResult:
    """Generate SQL from natural language.

    Args:
        nl: Natural language description
        dialect: Target dialect
        table_hint: Optional table name hint

    Returns:
        NL2SQLResult from the backend
    """
    gen = NL2SQLGenerator(default_dialect=dialect)
    return gen.generate(nl, dialect=dialect, table_hint=table_hint)


# ---------------------------------------------------------------------------
# Static data
# ---------------------------------------------------------------------------
from backend.core.config import SUPPORTED_DIALECTS, get_dialect_ui_info
from backend.utils.validators import split_sql_statements

DIALECTS = SUPPORTED_DIALECTS
DIALECT_INFO = get_dialect_ui_info()


def get_dialect_label(dialect: str) -> str:
    """Get formatted dialect label with icon."""
    info = DIALECT_INFO.get(dialect, {})
    icon = info.get("icon", "📄")
    return f"{icon} {dialect.upper()}"


# ---------------------------------------------------------------------------
# Static data loading
# ---------------------------------------------------------------------------
import json
from pathlib import Path


@st.cache_data
def load_data_v2() -> tuple[dict, dict]:
    """Load static data (types, functions) with caching.

    Returns:
        Tuple of (types_data, funcs_data)
    """
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
