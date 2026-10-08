#!/usr/bin/env python3
"""P8 NL2SQL pipeline: aggregation extraction (moved from nl2sql_legacy).

``extract_aggregations`` is a thin parameterized wrapper over
``nl2sql_components.aggregations.extract_aggregations`` — it fills the
canonical ``COLUMN_PATTERNS`` when none are supplied so the legacy
``self._extract_aggregations(text)`` call-shape works unchanged.
"""
from typing import Dict, List, Optional

from ..nl2sql_components.aggregations import (
    extract_aggregations as _extract_aggregations_impl,
)
from ..nl2sql_components.mappings import COLUMN_PATTERNS


def extract_aggregations(
    text: str, column_patterns: Optional[Dict[str, str]] = None
) -> List[str]:
    """Extract aggregation expressions from text.

    Returns a list of SQL aggregate expressions, e.g.
    ``['COUNT(*)', 'SUM(amount)']``.  An empty list means no
    aggregation was requested.
    """
    return _extract_aggregations_impl(text, column_patterns or COLUMN_PATTERNS)
