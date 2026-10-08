#!/usr/bin/env python3
"""Canonical metadata for SQL Dialect Master.

Single source of truth for product counts, version facts, and
dialect information. Every public surface (API, README verifier,
frontend) must derive its displayed numbers from this module rather
than from hardcoded literals.

Design rules:
- Counts (functions, types, rules, dialects) are computed at import
  time from the canonical data files / engine objects.
- Version constants live here and are the sole release source
  (``PROJECT_VERSION`` / ``API_VERSION``).
- The frontend architecture version is deliberately separate from
  the product version: "Frontend v2" is not "release v2.0".
"""
from __future__ import annotations

# ── Release version facts (sole source of truth) ────────────────────────
PROJECT_VERSION = "1.1.1"
API_VERSION = "1.1.1"
# Frontend v2 architecture — independent of the product release version.
FRONTEND_ARCHITECTURE_VERSION = 2


def _canonical_counts() -> dict:
    """Compute dialect / function / type / rule counts from data files."""
    import json
    from pathlib import Path

    base = Path(__file__).parent
    dialects, functions, types = 0, 0, 0
    type_file = base / "type_mapping.json"
    if type_file.exists():
        with type_file.open(encoding="utf-8") as f:
            data = json.load(f)
        dialects = len(data.get("dialects", []))
        types = len(data.get("mappings", {}))
    func_file = base / "functions_db.json"
    if func_file.exists():
        with func_file.open(encoding="utf-8") as f:
            fdata = json.load(f)
        functions = len(fdata.get("functions", []))
    return {"dialects": dialects, "functions": functions, "types": types}


_counts = _canonical_counts()

SUPPORTED_DIALECTS_COUNT = _counts["dialects"]
FUNCTION_COUNT = _counts["functions"]
TYPE_COUNT = _counts["types"]

# Rule count depends on the RuleEngine; compute lazily to keep the
# import graph clean. Uses the same engine instance the transpiler
# uses, so RULE_COUNT() matches the API's reported rule count.
def RULE_COUNT() -> int:
    """Number of active conversion rules in the RuleEngine."""
    from backend.core.post_processor import PostProcessor

    return len(PostProcessor().engine.rules)


__all__ = [
    "PROJECT_VERSION",
    "API_VERSION",
    "FRONTEND_ARCHITECTURE_VERSION",
    "SUPPORTED_DIALECTS_COUNT",
    "FUNCTION_COUNT",
    "TYPE_COUNT",
    "RULE_COUNT",
]
