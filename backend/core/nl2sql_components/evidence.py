#!/usr/bin/env python3
"""Evidence-based confidence model for NL2SQL generation.

Replaces opaque ``confidence += 0.1`` heuristic increments with a
structured list of named evidence items.  Each item records:

    evidence_id  - stable identifier for the evidence source
    label        - human-readable description
    weight       - contribution to the confidence score (signed)

The confidence score is the sum of all item weights, clamped to [0, 1],
exactly matching the previous heuristic's numeric output for the
same inputs.  Consumers can inspect the items list to understand
*why* a result was given its score.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EvidenceItem:
    """A single evidence item contributing to the confidence score.

    Attributes:
        evidence_id: Stable identifier, e.g. "table_known" or "parse_ok".
        label:      Human-readable description shown to the user.
        weight:      Signed contribution to the confidence score.
        detail:      Optional machine-readable context (table name, parse error, etc.).
    """
    evidence_id: str
    label: str
    weight: float
    detail: Optional[str] = None


@dataclass
class GenerationEvidence:
    """Structured evidence backing a generated SQL confidence score.

    Holds the full list of EvidenceItems and a computed score.
    The score is the sum of all weights, clamped to [0.0, 1.0],
    matching the previous heuristic confidence exactly.

    Use ``GenerationEvidence.score`` as the ``confidence`` value and
    pass ``GenerationEvidence.items`` as the evidence trail.
    """
    items: List[EvidenceItem] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Clamped sum of all item weights (matches legacy heuristic range)."""
        return max(0.0, min(1.0, sum(i.weight for i in self.items)))

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "items": [
                {
                    "evidence_id": i.evidence_id,
                    "label": i.label,
                    "weight": i.weight,
                    "detail": i.detail,
                }
                for i in self.items
            ],
        }


# ── Evidence ID constants ──────────────────────────────────────────────
# Use these instead of raw string literals so the IDs are stable
# across refactors and can be grepped.

# Table / schema evidence
EVIDENCE_TABLE_KNOWN = "table_known"
EVIDENCE_TABLE_UNKNOWN = "table_unknown"

# Column / aggregate evidence
EVIDENCE_COLUMNS_EXPLICIT = "columns_explicit"
EVIDENCE_COLUMNS_WILDCARD = "columns_wildcard"

# Predicate / condition evidence
EVIDENCE_CONDITIONS_PRESENT = "conditions_present"

# Relationship / join evidence
EVIDENCE_JOIN_KNOWN = "join_known"
EVIDENCE_JOIN_UNKNOWN = "join_unknown"

# Aggregation evidence
EVIDENCE_AGGREGATION_PRESENT = "aggregation_present"

# Ordering / limit / group-by evidence
EVIDENCE_GROUP_BY = "group_by"
EVIDENCE_ORDERING = "ordering"
EVIDENCE_LIMIT = "limit"

# Generated SQL structural evidence
EVIDENCE_PARSE_OK = "target_parse_ok"
EVIDENCE_PARSE_FAIL = "target_parse_fail"

# Template evidence
EVIDENCE_TEMPLATE_MATCHED = "template_matched"

__all__ = [
    "EvidenceItem",
    "GenerationEvidence",
    "EVIDENCE_TABLE_KNOWN",
    "EVIDENCE_TABLE_UNKNOWN",
    "EVIDENCE_COLUMNS_EXPLICIT",
    "EVIDENCE_COLUMNS_WILDCARD",
    "EVIDENCE_CONDITIONS_PRESENT",
    "EVIDENCE_JOIN_KNOWN",
    "EVIDENCE_JOIN_UNKNOWN",
    "EVIDENCE_AGGREGATION_PRESENT",
    "EVIDENCE_GROUP_BY",
    "EVIDENCE_ORDERING",
    "EVIDENCE_LIMIT",
    "EVIDENCE_PARSE_OK",
    "EVIDENCE_PARSE_FAIL",
    "EVIDENCE_TEMPLATE_MATCHED",
]
