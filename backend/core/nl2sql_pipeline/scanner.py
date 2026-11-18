"""NL2SQL-specific lexical masking helpers."""

from __future__ import annotations

from ..p1_sql_scanner import mask_non_executable


def mask_nl2sql_non_executable(
    text: str,
    dialect: str | None = None,
) -> str:
    """Mask literals/comments while preserving natural-language possessives.

    The shared SQL scanner keeps its strict default. NL2SQL prompts also use
    forms such as ``yesterday's orders`` and ``user's name``; the optional
    scanner mode recognizes only those possessive apostrophes and preserves
    all character positions for later span masking.
    """
    return mask_non_executable(
        text,
        dialect=dialect,
        allow_possessive=True,
    )


__all__ = ["mask_nl2sql_non_executable"]
