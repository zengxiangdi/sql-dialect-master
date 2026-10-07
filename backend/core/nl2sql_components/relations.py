#!/usr/bin/env python3
"""NL2SQL relation extraction: joins, join-key inference, relational keywords.

The join-key knowledge base (``JOIN_KEY_PATTERNS``) is the single
canonical source for inter-table relationships. Unknown relationships
return ``None`` so the caller can fail closed instead of fabricating
conditions.
"""
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

# Canonical join-key knowledge base.
# Pairs are stored both ways so lookups are order-independent.
JOIN_KEY_PATTERNS: Dict[tuple, str] = {
    ("users", "orders"): "users.id = orders.user_id",
    ("orders", "users"): "orders.user_id = users.id",
    ("users", "transactions"): "users.id = transactions.user_id",
    ("transactions", "users"): "transactions.user_id = users.id",
    ("orders", "products"): "orders.product_id = products.id",
    ("products", "orders"): "products.id = orders.product_id",
    ("users", "products"): "users.id = products.user_id",
    ("products", "users"): "products.user_id = users.id",
    ("employees", "departments"): "employees.dept_id = departments.id",
    ("departments", "employees"): "departments.id = employees.dept_id",
    ("orders", "payments"): "orders.id = payments.order_id",
    ("payments", "orders"): "payments.order_id = orders.id",
    ("customers", "orders"): "customers.id = orders.customer_id",
    ("orders", "customers"): "orders.customer_id = customers.id",
}

# Negative relational existence keywords -> NOT EXISTS
_NOT_EXISTS_KEYWORDS = [
    "without", "not have", "no ",
    "who don't have", "who doesn't have",
    "who do not have", "who does not have",
]

# Positive relational existence keywords -> EXISTS
_EXISTS_KEYWORDS = [
    "who have", "who has", "that have", "that has",
    "with orders", "with customers",
    "with users", "with employees",
    "with invoices", "with payments", "with transactions",
    "with suppliers", "with products",
    "who placed", "who made", "who created", "who submitted",
]


# Explicit physical JOIN keywords, each mapped to its structured kind.
# Matched as whole words / substrings against the full text — never as
# "the first token of the sentence" (the legacy split()[0] bug).
_JOIN_KIND_KEYWORDS: Dict[str, str] = {
    "left join": "LEFT",
    "右连接": "RIGHT",
    "right join": "RIGHT",
    "inner join": "INNER",
    "内连接": "INNER",
    "outer join": "OUTER",
    "cross join": "CROSS",
}


@dataclass(frozen=True)
class JoinSpec:
    """Structured physical-join intent parsed from natural language.

    ``kind`` is one of ``"LEFT" | "RIGHT" | "INNER" | "OUTER" | "CROSS"
    | "JOIN"`` (JOIN = unqualified, defaults to inner). ``matched_text``
    records which keyword fired, for evidence.
    """

    kind: str
    matched_text: str


def parse_join_spec(text: str) -> Optional[JoinSpec]:
    """Parse an explicit physical-join keyword into a structured JoinSpec.

    Returns ``None`` when the text carries no physical-join intent
    (e.g. relational-existence phrases like "users who have orders"), in
    which case the caller falls back to its EXISTS/JOIN inference.

    Keywords are located anywhere in the text via whole-phrase
    matching — the join type is never inferred from the first word of the
    sentence.
    """
    lowered = text.lower()
    for keyword, kind in _JOIN_KIND_KEYWORDS.items():
        if keyword.isascii():
            # English: whole-word, case-insensitive.
            if re.search(r"\b" + re.escape(keyword) + r"\b", lowered):
                return JoinSpec(kind=kind, matched_text=keyword)
        else:
            # Chinese (or any non-ASCII keyword): direct substring.
            if keyword in text:
                return JoinSpec(kind=kind, matched_text=keyword)
    # Unqualified physical "join" that is not part of a known qualified
    # keyword — default to inner.
    if re.search(r"\bjoin\b", lowered):
        return JoinSpec(kind="JOIN", matched_text="join")
    return None


def guess_join_key(table1: str, table2: str) -> Optional[str]:
    """Return the canonical join condition between two tables, or None.

    None means the relationship is unknown; the caller must not
    fabricate a condition.
    """
    return JOIN_KEY_PATTERNS.get((table1, table2))


def extract_joins(
    text: str,
    table_patterns: Dict[str, str],
) -> List[Dict]:
    """Extract structured join contexts from text.

    Detects relational existence patterns (e.g. "users who have orders")
    and returns one dict per additional table, keyed as:

        type      - "EXISTS", "NOT EXISTS" or "JOIN"
        table     - the related table name
        subject   - the main (first-appearing) table name
        condition - join key string, or None for unknown relationships
        relational - True when type is EXISTS/NOT EXISTS
    """
    joins = []
    # Collect unique tables in text-appearance order (first occurrence wins).
    # Exclude "order" when it is part of an "order by" sorting clause.
    table_occurrences = []
    for pattern, table in table_patterns.items():
        if pattern == "order" and re.search(r"\border\b\s+by\b", text, re.IGNORECASE):
            continue
        if re.search(r"\b" + re.escape(pattern) + r"\b", text) and table not in [t for _, t in table_occurrences]:
            table_occurrences.append((text.find(pattern), table))
    tables_found = [t for _, t in sorted(table_occurrences)]
    if len(tables_found) >= 2:
        join_spec = parse_join_spec(text)
        if any(k in text for k in _NOT_EXISTS_KEYWORDS):
            join_type = "NOT EXISTS"
            relational = True
        elif any(k in text for k in _EXISTS_KEYWORDS):
            join_type = "EXISTS"
            relational = True
        elif join_spec is not None:
            # Structured physical-join intent.  Unqualified "JOIN" normalizes
            # to inner; qualified kinds map directly to their SQL keyword.
            join_type = "INNER" if join_spec.kind == "JOIN" else join_spec.kind
            relational = False
        else:
            join_type = "JOIN"
            relational = False

        main_table = tables_found[0]
        for other_table in tables_found[1:]:
            join_key = guess_join_key(main_table, other_table)
            record = {
                "type": join_type,
                "table": other_table,
                "subject": main_table,
                "condition": join_key,
                "relational": relational,
                "join_spec": join_spec,
            }
            if join_key is None:
                # Unknown relationship - do not fabricate a condition.
                # Carry both sides of the pair so downstream fail-closed
                # messages can name the actual unresolved relationship.
                joins.append(record)
                continue
            joins.append(record)
    return joins


def has_relational_keyword(text: str) -> bool:
    """Check if text contains any relational existence keyword."""
    all_keywords = _NOT_EXISTS_KEYWORDS + _EXISTS_KEYWORDS
    return any(pattern in text for pattern in all_keywords)
