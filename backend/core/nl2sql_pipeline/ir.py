#!/usr/bin/env python3
"""P8 NL2SQL pipeline: Query IR.

The IR is the structured intermediate representation produced by the
resolution stages and consumed by the renderer.  In P8 it mirrors the
flat positional-argument shape of the legacy ``_build_sql_enhanced``
call, plus the ``evidence`` accumulator, so the migration is
behavior-preserving.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from ..nl2sql_components.evidence import GenerationEvidence


@dataclass
class QueryIR:
    """Structured intermediate representation for an NL2SQL query.

    Mirrors the positional-argument shape of the legacy
    ``_build_sql_enhanced`` call.  ``conditions`` may be a ``list`` of
    predicate strings or a single ``str`` — the renderer handles both
    (mirroring current legacy code).
    """

    operation: str
    table: str
    columns: List[str]
    conditions: Union[List[str], str]
    aggregations: List[str]
    group_by: List[str]
    ordering: Optional[Tuple[str, str]]
    limit: Optional[int]
    joins: List[Dict]
    distinct: bool
    dialect: str
    evidence: GenerationEvidence = field(default_factory=GenerationEvidence)


def build_ir(
    operation: str,
    table: str,
    columns: List[str],
    conditions: Union[List[str], str],
    aggregations: List[str],
    group_by: List[str],
    ordering: Optional[Tuple[str, str]],
    limit: Optional[int],
    joins: List[Dict],
    distinct: bool,
    dialect: str,
) -> QueryIR:
    """Thin positional-arg adapter mirroring the legacy call site.

    Constructs a ``QueryIR`` with a fresh ``GenerationEvidence``
    accumulator, identical to what the legacy code did implicitly.
    """
    return QueryIR(
        operation=operation,
        table=table,
        columns=columns,
        conditions=conditions,
        aggregations=aggregations,
        group_by=group_by,
        ordering=ordering,
        limit=limit,
        joins=joins,
        distinct=distinct,
        dialect=dialect,
    )
