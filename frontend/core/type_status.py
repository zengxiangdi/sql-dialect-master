"""Type-mapping status classification for the Types page.

Status priority (both-missing must never masquerade as exact):

1. ``missing``         — both dialects lack a mapping (``N/A → N/A``)
2. ``source_missing``  — the source dialect lacks a mapping
3. ``target_missing``  — the target dialect lacks a mapping
4. ``exact``           — both sides carry the same real mapping
5. ``mapped``          — different real mappings on both sides
"""
from __future__ import annotations

_MISSING = "N/A"


def classify_mapping_status(src_type: str, tgt_type: str) -> str:
    """Classify one source→target type mapping cell for display."""
    if src_type == _MISSING and tgt_type == _MISSING:
        return "missing"
    if src_type == _MISSING:
        return "source_missing"
    if tgt_type == _MISSING:
        return "target_missing"
    if src_type == tgt_type:
        return "exact"
    return "mapped"
