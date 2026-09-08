"""Focused fix for inclusive comparison precedence in legacy NL2SQL parsing."""

import re

from .nl2sql import NL2SQLGenerator


_original_extract_conditions = NL2SQLGenerator._extract_conditions_enhanced


def _extract_conditions_with_comparison_precedence(self, text: str, original: str):
    """Preserve >= and <= semantics when inclusive Chinese phrases contain >/< keywords."""
    conditions = _original_extract_conditions(self, text, original)

    if any(keyword in text for keyword in ["大于等于", "不小于"]):
        conditions = [
            re.sub(r"\s>\s(\d+\.?\d*)$", r" >= \1", condition, count=1)
            for condition in conditions
        ]

    if any(keyword in text for keyword in ["小于等于", "不大于"]):
        conditions = [
            re.sub(r"\s<\s(\d+\.?\d*)$", r" <= \1", condition, count=1)
            for condition in conditions
        ]

    return conditions


NL2SQLGenerator._extract_conditions_enhanced = _extract_conditions_with_comparison_precedence
