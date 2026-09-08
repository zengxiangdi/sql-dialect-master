"""Boolean condition extraction for NL2SQL.

The existing NL2SQL generator already handles single predicates. This module
adds a small, focused layer for queries that explicitly combine multiple
predicates with AND/OR, while leaving the legacy extractor as the fallback.
"""
import re
from typing import List, Optional, Tuple


_COMPARISON_PATTERNS = (
    re.compile(
        r"\b(price|quantity|amount|age|score|rating|views|clicks)\s+"
        r"(greater(?:\s+than)?|more\s+than|above|over|less(?:\s+than)?|"
        r"below|under|equal(?:\s+to)?|equals)\s+"
        r"([0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(price|quantity|amount|age|score|rating|views|clicks)\s*"
        r"(>=|<=|!=|=|>|<)\s*([0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    ),
)

_STATUS_PATTERN = re.compile(
    r"\bstatus\s+(active|enabled|valid|inactive|disabled|invalid|"
    r"completed|done|pending|paid|unpaid)\b",
    re.IGNORECASE,
)

_STATUS_CONDITIONS = {
    "active": "status = 'active'",
    "enabled": "status = 'active'",
    "valid": "status = 'active'",
    "inactive": "status = 'inactive'",
    "disabled": "status = 'inactive'",
    "invalid": "status = 'inactive'",
    "completed": "status = 'completed'",
    "done": "status = 'completed'",
    "pending": "status = 'pending'",
    "paid": "status = 'paid'",
    "unpaid": "status = 'unpaid'",
}


def _normalize_operator(raw: str) -> str:
    normalized = raw.lower()
    if normalized.startswith(("greater", "more", "above", "over")):
        return ">"
    if normalized.startswith(("less", "below", "under")):
        return "<"
    if normalized.startswith(("equal", "equals")):
        return "="
    return normalized.upper()


def extract_boolean_conditions(text: str) -> Optional[List[str]]:
    """Return a single SQL boolean expression when multiple predicates are explicit."""
    matches: List[Tuple[int, int, str]] = []

    for pattern in _COMPARISON_PATTERNS:
        for match in pattern.finditer(text):
            column, raw_operator, value = match.groups()
            predicate = f"{column} {_normalize_operator(raw_operator)} {value}"
            matches.append((match.start(), match.end(), predicate))

    for match in _STATUS_PATTERN.finditer(text):
        status = match.group(1).lower()
        matches.append((match.start(), match.end(), _STATUS_CONDITIONS[status]))

    matches.sort(key=lambda item: item[0])
    if len(matches) < 2:
        return None

    connectors: List[str] = []
    for left, right in zip(matches, matches[1:]):
        separator = text[left[1] : right[0]].lower()
        if re.search(r"\b(or|或者)\b|或", separator):
            connectors.append("OR")
        elif re.search(r"\b(and|以及|并且)\b|且", separator):
            connectors.append("AND")
        else:
            return None

    expression = f"({matches[0][2]})"
    for connector, match in zip(connectors, matches[1:]):
        expression += f" {connector} ({match[2]})"
    return [expression]
