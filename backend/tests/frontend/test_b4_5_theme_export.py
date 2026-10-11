"""B4-5 — theme export must serialize real dataclass tokens.

``ColorTokens`` is a frozen dataclass; calling ``model_dump_json`` on it
fails.  The export interface stays and produces stable, valid JSON that
round-trips through the existing theme validator.
"""
from __future__ import annotations

import json

import pytest

from frontend.core.design_tokens import ColorTokens, DARK
from frontend.core.themes import export_theme, validate_theme_json


class TestB4_5_ThemeExport:
    def test_export_returns_parseable_json(self):
        exported = export_theme(DARK)
        data = json.loads(exported)
        assert isinstance(data, dict)
        assert data  # not empty

    def test_export_contains_every_token_field(self):
        exported = export_theme(DARK)
        data = json.loads(exported)
        for field_name in ColorTokens.__dataclass_fields__:
            assert field_name in data, f"missing field {field_name}"

    def test_export_values_match_source_tokens(self):
        exported = export_theme(DARK)
        data = json.loads(exported)
        for field_name in ColorTokens.__dataclass_fields__:
            assert data[field_name] == getattr(DARK, field_name)

    def test_export_round_trips_through_validator(self):
        exported = export_theme(DARK)
        validated = validate_theme_json(exported)
        assert validated["bg"] == DARK.bg

    def test_invalid_json_still_rejected(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            validate_theme_json("{not json")
