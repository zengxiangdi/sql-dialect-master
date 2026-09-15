"""Design tokens for SQL Dialect Master v2.

Defines a single source of truth for colors, typography, spacing, and
semantic status values used across the entire frontend.

Two themes only: Dark (default) and Light.
"""
from dataclasses import dataclass
from typing import Literal

ThemeName = Literal["dark", "light"]


@dataclass(frozen=True)
class ColorTokens:
    """Complete color palette for one theme."""

    # Background layers
    bg: str
    surface: str
    surface_elevated: str

    # Borders and dividers
    border: str
    border_subtle: str

    # Text
    text_primary: str
    text_secondary: str
    text_muted: str
    text_on_accent: str

    # Semantic colors
    accent: str
    success: str
    warning: str
    danger: str
    info: str

    # Component states
    input_bg: str
    input_border: str
    input_border_focus: str
    hover_bg: str
    selected_bg: str


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

DARK: ColorTokens = ColorTokens(
    bg="#0B0D10",
    surface="#111418",
    surface_elevated="#171B21",
    border="#262B33",
    border_subtle="#1E2229",
    text_primary="#E6EAF0",
    text_secondary="#9AA4B2",
    text_muted="#667085",
    text_on_accent="#0B0D10",
    accent="#4F8CFF",
    success="#2FBF71",
    warning="#D9A441",
    danger="#E25555",
    info="#5B9CFF",
    input_bg="#171B21",
    input_border="#262B33",
    input_border_focus="#4F8CFF",
    hover_bg="#1E2229",
    selected_bg="#4F8CFF18",
)

LIGHT: ColorTokens = ColorTokens(
    bg="#F7F8FA",
    surface="#FFFFFF",
    surface_elevated="#FFFFFF",
    border="#E4E7EC",
    border_subtle="#EEF0F4",
    text_primary="#101828",
    text_secondary="#475467",
    text_muted="#667085",
    text_on_accent="#FFFFFF",
    accent="#2563EB",
    success="#15803D",
    warning="#B45309",
    danger="#DC2626",
    info="#2563EB",
    input_bg="#FFFFFF",
    input_border="#E4E7EC",
    input_border_focus="#2563EB",
    hover_bg="#F4F5F7",
    selected_bg="#2563EB18",
)

THEMES: dict[ThemeName, ColorTokens] = {
    "dark": DARK,
    "light": LIGHT,
}

# ---------------------------------------------------------------------------
# Semantic status constants
# ---------------------------------------------------------------------------

STATUS_VALID = "valid"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"
STATUS_INFO = "info"
STATUS_NEUTRAL = "neutral"

SEMANTIC_STATUS_LABELS: dict[str, str] = {
    "equivalent": "Equivalent",
    "structurally_equivalent": "Structurally Equivalent",
    "potentially_different": "Potentially Different",
    "definitely_different": "Definitely Different",
    "unknown": "Unknown",
    "parse_error": "Parse Error",
}

SEMANTIC_STATUS_COLOR: dict[str, str] = {
    "equivalent": "success",
    "structurally_equivalent": "success",
    "potentially_different": "warning",
    "definitely_different": "danger",
    "unknown": "warning",
    "parse_error": "error",
}
