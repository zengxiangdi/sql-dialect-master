#!/usr/bin/env python3
"""Frontend theme tests."""
from __future__ import annotations

import pytest

from frontend.core.design_tokens import DARK, LIGHT, THEMES, ColorTokens
from frontend.core.themes import get_theme, list_themes, validate_theme_json
from frontend.core.styles import generate_css


class TestDesignTokens:
    """Test design token constants."""

    def test_dark_theme_colors(self) -> None:
        """Dark theme should have correct color values."""
        assert DARK.bg == "#0B0D10"
        assert DARK.surface == "#111418"
        assert DARK.accent == "#4F8CFF"
        assert DARK.text_primary == "#E6EAF0"
        assert DARK.success == "#2FBF71"
        assert DARK.warning == "#D9A441"
        assert DARK.danger == "#E25555"

    def test_light_theme_colors(self) -> None:
        """Light theme should have correct color values."""
        assert LIGHT.bg == "#F7F8FA"
        assert LIGHT.surface == "#FFFFFF"
        assert LIGHT.accent == "#2563EB"
        assert LIGHT.text_primary == "#101828"
        assert LIGHT.success == "#15803D"
        assert LIGHT.warning == "#B45309"
        assert LIGHT.danger == "#DC2626"

    def test_themes_dict_contains_both(self) -> None:
        """THEMES dict should contain both dark and light."""
        assert "dark" in THEMES
        assert "light" in THEMES
        assert THEMES["dark"] == DARK
        assert THEMES["light"] == LIGHT


class TestThemeManagement:
    """Test theme management functions."""

    def test_get_theme_dark(self) -> None:
        """get_theme('dark') should return DARK tokens."""
        theme = get_theme("dark")
        assert theme == DARK
        assert isinstance(theme, ColorTokens)

    def test_get_theme_light(self) -> None:
        """get_theme('light') should return LIGHT tokens."""
        theme = get_theme("light")
        assert theme == LIGHT

    def test_get_theme_fallback(self) -> None:
        """get_theme with unknown theme should fallback to dark."""
        theme = get_theme("nonexistent")
        assert theme == DARK

    def test_list_themes(self) -> None:
        """list_themes should return ['dark', 'light']."""
        themes = list_themes()
        assert themes == ["dark", "light"]


class TestCSSGeneration:
    """Test CSS generation from themes."""

    def test_dark_css_contains_variables(self) -> None:
        """Dark theme CSS should contain all custom properties."""
        css = generate_css(DARK)
        assert "--sdm-bg:" in css
        assert "--sdm-accent:" in css
        assert "--sdm-success:" in css
        assert "#0B0D10" in css  # dark bg value

    def test_light_css_contains_variables(self) -> None:
        """Light theme CSS should contain all custom properties."""
        css = generate_css(LIGHT)
        assert "--sdm-bg:" in css
        assert "#F7F8FA" in css  # light bg value

    def test_css_is_valid_structure(self) -> None:
        """Generated CSS should have proper structure."""
        css = generate_css(DARK)
        assert ":root" in css
        assert "}" in css
        assert "<style>" in css


class TestThemeValidation:
    """Test theme JSON validation."""

    def test_valid_theme_json(self) -> None:
        """Valid theme JSON should pass validation."""
        import json
        theme = {
            "bg": "#000000",
            "surface": "#111111",
            "surface_elevated": "#222222",
            "border": "#333333",
            "border_subtle": "#444444",
            "text_primary": "#ffffff",
            "text_secondary": "#aaaaaa",
            "text_muted": "#888888",
            "text_on_accent": "#000000",
            "accent": "#4F8CFF",
            "success": "#2FBF71",
            "warning": "#D9A441",
            "danger": "#E25555",
            "info": "#5B9CFF",
            "input_bg": "#171B21",
            "input_border": "#262B33",
            "input_border_focus": "#4F8CFF",
            "hover_bg": "#1E2229",
            "selected_bg": "#4F8CFF18",
        }
        result = validate_theme_json(json.dumps(theme))
        assert result == theme

    def test_invalid_json_raises(self) -> None:
        """Invalid JSON should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            validate_theme_json("{invalid")

    def test_missing_keys_raises(self) -> None:
        """JSON missing required keys should raise ValueError."""
        import json
        incomplete = {"bg": "#000000"}
        with pytest.raises(ValueError, match="Missing required theme keys"):
            validate_theme_json(json.dumps(incomplete))
