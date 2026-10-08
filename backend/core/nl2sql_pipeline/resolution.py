#!/usr/bin/env python3
"""P8 NL2SQL pipeline: entity and relation resolution (moved from nl2sql_legacy).

Thin function-level adapters over the existing ``nl2sql_components``
modules.  Signatures mirror the legacy instance-method forms so the
facade's ``super()`` overrides continue to resolve unchanged.
"""
from typing import Dict, List, Optional

from ..nl2sql_components.mappings import COLUMN_PATTERNS, TABLE_PATTERNS
from ..nl2sql_components.relations import (
    extract_joins as _extract_joins_impl,
    guess_join_key as _guess_join_key_impl,
    has_relational_keyword as _has_relational_keyword_impl,
)
from ..nl2sql_components.core_extract import (
    extract_columns as _extract_columns_impl,
    extract_table as _extract_table_impl,
    extract_table_subject as _extract_table_subject_impl,
    named_tables as _named_tables_impl,
)


# ── Entity resolution ────────────────────────────────────────────────────────

def extract_table(text: str, table_patterns: Optional[Dict[str, str]] = None) -> str:
    """Extract table name from text (delegates to core_extract)."""
    return _extract_table_impl(text, table_patterns or TABLE_PATTERNS)


def extract_table_subject(
    text: str, table_patterns: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """Extract the subject table (first appearing in text) for D2 relational queries."""
    return _extract_table_subject_impl(text, table_patterns or TABLE_PATTERNS)


def named_tables(text: str, table_patterns: Optional[Dict[str, str]] = None) -> list:
    """Return the distinct table names the text mentions."""
    return _named_tables_impl(text, table_patterns or TABLE_PATTERNS)


def extract_columns(
    text: str, column_patterns: Optional[Dict[str, str]] = None
) -> list:
    """Extract column names from text (delegates to core_extract)."""
    return _extract_columns_impl(text, column_patterns or COLUMN_PATTERNS)


# ── Relation resolution ───────────────────────────────────────────────────────

def extract_joins(text: str, table_patterns: Optional[Dict[str, str]] = None) -> list:
    """Extract JOIN information from text.

    Detects relational existence patterns (e.g. "users who have orders")
    and returns structured join contexts for EXISTS-based SQL generation.
    """
    return _extract_joins_impl(text, table_patterns or TABLE_PATTERNS)


def guess_join_key(table1: str, table2: str) -> Optional[str]:
    """Guess the join key between two tables.  Returns None for unknown
    relationships instead of guessing (fail-closed)."""
    return _guess_join_key_impl(table1, table2)


def has_relational_keyword(text: str) -> bool:
    """Check if text contains relational existence keywords (D2)."""
    return _has_relational_keyword_impl(text)
