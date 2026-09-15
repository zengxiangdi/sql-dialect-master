"""Shared HTML-safe escaping utilities.

Replaces the ad-hoc `_esc()` function that lived in app_context.py.
Uses markupsafe.escape which is already a transitive dependency of
Streamlit and handles all HTML entity encoding correctly including
attribute contexts.
"""
from markupsafe import escape as html_escape

# Re-export under a project-specific name for clarity
esc = html_escape

__all__ = ["esc"]
