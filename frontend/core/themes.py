"""Theme management for SQL Dialect Master v2.

Provides theme switching (Dark / Light) and CSS variable generation.
Custom themes from the old system are no longer supported.
"""
import json

from .design_tokens import THEMES, ColorTokens, ThemeName

DEFAULT_THEME: ThemeName = "dark"


def get_theme(theme_name: str) -> ColorTokens:
    """Get theme by name with fallback to default.

    Args:
        theme_name: Theme name — 'dark' or 'light'

    Returns:
        ColorTokens for the requested theme
    """
    return THEMES.get(theme_name, THEMES[DEFAULT_THEME])


def list_themes() -> list[str]:
    """Return list of available theme keys."""
    return list(THEMES.keys())


def export_theme(theme: ColorTokens) -> str:
    """Export theme tokens to JSON string.

    Args:
        theme: ColorTokens instance

    Returns:
        JSON representation
    """
    return theme.model_dump_json(indent=2)


def validate_theme_json(json_str: str) -> dict:
    """Validate a theme JSON string without applying it.

    Args:
        json_str: JSON string to validate

    Returns:
        Parsed dictionary if valid

    Raises:
        ValueError: If JSON is invalid or missing required keys
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    required = {
        "bg", "surface", "surface_elevated", "border", "border_subtle",
        "text_primary", "text_secondary", "text_muted", "text_on_accent",
        "accent", "success", "warning", "danger", "info",
        "input_bg", "input_border", "input_border_focus",
        "hover_bg", "selected_bg",
    }
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing required theme keys: {', '.join(sorted(missing))}")
    return data
