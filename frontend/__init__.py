"""SQL Dialect Master v2 — Frontend package.

Public exports for the v2 frontend architecture.
"""
from __future__ import annotations

from frontend.core.design_tokens import DARK, LIGHT, THEMES, ColorTokens
from frontend.core.styles import generate_css

__all__ = ["DARK", "LIGHT", "THEMES", "ColorTokens", "generate_css"]
