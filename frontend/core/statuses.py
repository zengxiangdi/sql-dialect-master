"""Canonical presentation statuses shared by view models and UI components."""
from __future__ import annotations

from typing import Literal

from frontend.core.design_tokens import ColorTokens

StatusKind = Literal["valid", "warning", "error", "info", "neutral"]

_STATUS_ALIASES: dict[str, StatusKind] = {
    "valid": "valid", "success": "valid", "ok": "valid",
    "equivalent": "valid", "structurally_equivalent": "valid", "high": "valid",
    "warning": "warning", "review": "warning", "unknown": "warning",
    "potentially_different": "warning",
    "error": "error", "danger": "error", "parse_error": "error", "low": "error",
    "different": "error", "definitely_different": "error",
    "info": "info", "neutral": "neutral", "pending": "neutral",
}
_STATUS_TOKEN: dict[StatusKind, str] = {
    "valid": "success", "warning": "warning", "error": "danger",
    "info": "info", "neutral": "text_muted",
}


def normalize_status(status: object) -> StatusKind:
    """Normalize domain statuses and legacy color names to the UI vocabulary."""
    if not isinstance(status, str):
        return "neutral"
    return _STATUS_ALIASES.get(status, "neutral")


def status_color(status: object, theme: ColorTokens) -> str:
    """Resolve every status through the same theme token mapping."""
    return getattr(theme, _STATUS_TOKEN[normalize_status(status)])
