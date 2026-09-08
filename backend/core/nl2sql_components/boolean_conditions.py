"""Boolean condition extraction for NL2SQL.

Extract explicit comparison predicates and boolean connectors while preserving
normal SQL AND-over-OR precedence and user-supplied parentheses.
"""
import re
from typing import List, Optional, Tuple


_COMPARISON_PATTERNS = (
    re.compile(
        r"(?<![A-Za-z0-9_])(price|quantity|amount|age|score|rating|views|clicks)\s+"
        r"(greater(?:\s+than)?|more\s+than|above|over|less(?:\s+than)?|"
        r"below|under|equal(?:\s+to)?|equals)\s+"
        r"([0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Za-z0-9_])(price|quantity|amount|age|score|rating|views|clicks)\s*"
        r"(>=|<=|!=|=|>|<)\s*([0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(价格|数量|金额|年龄|得分|评分|浏览量|点击量)\s*"
        r"(大于等于|小于等于|不等于|大于|小于|超过|低于|等于)\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
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

_CN_COLUMNS = {
    "价格": "price",
    "数量": "quantity",
    "金额": "amount",
    "年龄": "age",
    "得分": "score",
    "评分": "rating",
    "浏览量": "views",
    "点击量": "clicks",
}

_CN_OPERATORS = {
    "大于等于": ">=",
    "小于等于": "<=",
    "不等于": "!=",
    "大于": ">",
    "小于": "<",
    "超过": ">",
    "低于": "<",
    "等于": "=",
}

_CONNECTOR_PATTERN = re.compile(r"\b(?:and|or)\b|以及|并且|且|或者|或|和", re.IGNORECASE)


def _normalize_operator(raw: str) -> str:
    normalized = raw.lower()
    if normalized.startswith(("greater", "more", "above", "over")):
        return ">"
    if normalized.startswith(("less", "below", "under")):
        return "<"
    if normalized.startswith(("equal", "equals")):
        return "="
    return _CN_OPERATORS.get(raw, normalized.upper())


def _comparison_matches(text: str) -> List[Tuple[int, int, str]]:
    matches: List[Tuple[int, int, str]] = []
    for pattern in _COMPARISON_PATTERNS:
        for match in pattern.finditer(text):
            first, raw_operator, value = match.groups()
            column = _CN_COLUMNS.get(first, first)
            matches.append((match.start(), match.end(), f"{column} {_normalize_operator(raw_operator)} {value}"))

    for match in _STATUS_PATTERN.finditer(text):
        status = match.group(1).lower()
        matches.append((match.start(), match.end(), _STATUS_CONDITIONS[status]))

    matches.sort(key=lambda item: (item[0], item[1]))
    deduped: List[Tuple[int, int, str]] = []
    for item in matches:
        if deduped and item[0] == deduped[-1][0] and item[1] <= deduped[-1][1]:
            continue
        deduped.append(item)
    return deduped


def extract_boolean_conditions(text: str) -> Optional[List[str]]:
    """Return one boolean SQL expression preserving connector precedence/grouping."""
    matches = _comparison_matches(text)
    if len(matches) < 2:
        return None

    tokens: List[str] = []
    prefix = text[: matches[0][0]]
    tokens.extend(char for char in prefix if char in "()")

    for index, current in enumerate(matches):
        tokens.append(f"({current[2]})")
        if index == len(matches) - 1:
            suffix = text[current[1] :]
            tokens.extend(char for char in suffix if char in "()")
            continue

        separator = text[current[1] : matches[index + 1][0]]
        events = []
        for paren in re.finditer(r"[()]", separator):
            events.append((paren.start(), paren.group(0)))
        connector_matches = list(_CONNECTOR_PATTERN.finditer(separator))
        if len(connector_matches) != 1:
            return None
        connector = connector_matches[0]
        events.append((connector.start(), connector.group(0)))
        events.sort(key=lambda item: item[0])
        for _, event in events:
            if event == "(" or event == ")":
                tokens.append(event)
            elif event:
                normalized = event.lower()
                tokens.append("OR" if normalized in {"or", "或者", "或"} else "AND")

    return [" ".join(tokens)]
