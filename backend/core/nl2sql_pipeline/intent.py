#!/usr/bin/env python3
"""P8 NL2SQL pipeline: intent analysis (moved from nl2sql_legacy).

Holds the tokenization / semantic-analysis step (``analyze_intent``)
and the text-parsing helpers (``parse_text``, ``detect_operation``)
that feed the resolution stages.
"""
import re
from typing import Any, Dict, Optional

from ..nl2sql_components.core_extract import detect_operation as _detect_operation_impl
from ..nl2sql_components.mappings import COLUMN_PATTERNS, KEYWORDS, TABLE_PATTERNS
from ..nl2sql_components.tokenizer import Tokenizer


def analyze_intent(text: str) -> Dict[str, Any]:
    """Tokenize text and perform semantic analysis.

    Returns the same dict shape the legacy
    ``_tokenize_and_analyze`` produced:
    ``tokens``, ``numbers``, ``quoted_strings``, ``tables``, ``columns``,
    ``operations``, ``is_chinese``, ``token_count``.
    """
    tokenizer = Tokenizer()
    tokens = tokenizer.tokenize(text)
    numbers = tokenizer.extract_numbers(text)
    quoted = tokenizer.extract_quoted_strings(text)

    detected_tables = [
        TABLE_PATTERNS[token]
        for token in tokens
        if token in TABLE_PATTERNS
    ]
    detected_columns = [
        COLUMN_PATTERNS[token]
        for token in tokens
        if token in COLUMN_PATTERNS
    ]
    detected_ops = [
        KEYWORDS[token]
        for token in tokens
        if token in KEYWORDS
    ]

    return {
        "tokens": tokens,
        "numbers": numbers,
        "quoted_strings": quoted,
        "tables": list(set(detected_tables)),
        "columns": list(set(detected_columns)),
        "operations": list(set(detected_ops)),
        "is_chinese": tokenizer.is_chinese(text),
        "token_count": len(tokens),
    }


def parse_text(text_lower: str, original: str) -> dict:
    """Parse and extract all elements from text (legacy ``_parse_text``)."""
    parsed = {
        "tables": [],
        "columns": [],
        "conditions": [],
        "aggregations": [],
        "time_range": None,
        "limit": None,
        "order": None,
        "joins": [],
    }
    # Word-boundary matching for tables to avoid false positives like "order" matching "orders"
    for pattern, table in TABLE_PATTERNS.items():
        if re.search(r'\b' + re.escape(pattern) + r'\b', text_lower) and table not in parsed["tables"]:
            parsed["tables"].append(table)
    # Word-boundary matching for columns
    for pattern, column in COLUMN_PATTERNS.items():
        if re.search(r'\b' + re.escape(pattern) + r'\b', text_lower) and column not in parsed["columns"]:
            parsed["columns"].append(column)
    numbers = re.findall(r"\d+", original)
    if numbers:
        parsed["numbers"] = numbers
    return parsed


def detect_operation(text: str) -> str:
    """Detect SQL operation type from text (delegates to core_extract)."""
    return _detect_operation_impl(text, KEYWORDS)
