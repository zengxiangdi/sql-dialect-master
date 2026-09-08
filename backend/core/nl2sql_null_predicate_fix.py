"""Focused fix for negative NULL predicate extraction in NL2SQL."""

import re

from .nl2sql import NL2SQLGenerator


_original_extract_conditions = NL2SQLGenerator._extract_conditions_enhanced


def _extract_conditions_with_negative_null_precedence(self, text: str, original: str):
    """Ensure negative NULL predicates do not also produce IS NULL."""
    negative_null = re.search(
        r"(?:\bis\s+not\s+null\b|\bnot\s+null\b|\bnot\s+empty\b|非空|不为空)",
        text,
        re.IGNORECASE,
    )
    positive_null = re.search(
        r"(?:\bis\s+null\b|\bnull\b|\bempty\b|为空|空值)",
        text,
        re.IGNORECASE,
    )
    if not negative_null or (positive_null and positive_null.start() < negative_null.start()):
        return _original_extract_conditions(self, text, original)

    sanitized_text = re.sub(
        r"\bis\s+not\s+null\b|\bnot\s+null\b|\bnot\s+empty\b|非空|不为空",
        "__SDM_NEGATIVE_NULL__",
        text,
        flags=re.IGNORECASE,
    )
    conditions = _original_extract_conditions(self, sanitized_text, original)
    conditions = [condition for condition in conditions if not condition.endswith(" IS NULL")]

    condition_column = None
    for pattern, column in self.COLUMN_PATTERNS.items():
        if pattern in text:
            condition_column = column
            break
    conditions.append(f"{condition_column or 'column'} IS NOT NULL")
    return conditions


NL2SQLGenerator._extract_conditions_enhanced = _extract_conditions_with_negative_null_precedence
