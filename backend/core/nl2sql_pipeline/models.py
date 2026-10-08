#!/usr/bin/env python3
"""P8 NL2SQL pipeline: result model.

``NL2SQLResult`` is the single canonical result dataclass.  It is re-exported
from every import path (``nl2sql``, ``nl2sql_legacy``, ``nl2sql_pipeline``)
so that ``from backend.core.nl2sql import NL2SQLResult as A`` and
``from backend.core.nl2sql_legacy import NL2SQLResult as B`` satisfy
``A is B``.
"""
from dataclasses import dataclass, field

from ..nl2sql_components.evidence import GenerationEvidence


@dataclass
class NL2SQLResult:
    """Result of NL2SQL generation."""

    success: bool = False
    input_text: str = ""
    sql: str | None = None
    dialect: str = ""
    explanation: str = ""
    confidence: float = 0.0
    # Structured evidence trail backing ``confidence``. Optional and
    # backward-compatible: consumers that only need the scalar score can
    # ignore this field.
    evidence: GenerationEvidence | None = None
    suggestions: list = field(default_factory=list)
    parsed_elements: dict = field(default_factory=dict)
