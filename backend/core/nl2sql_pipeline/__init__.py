"""P8 NL2SQL pipeline: named-stage modules extracted from nl2sql_legacy.

Each module corresponds to one stage of the target pipeline
(Intent → Entity Resolution → Relation Resolution → Predicate Resolution
→ Query IR → Dialect Renderer → AST Validation → Evidence/Confidence).

This package is internal to ``backend.core``; it is NOT re-exported from
``backend.core.__init__``.  The public facade is ``backend.core.nl2sql``.
"""
from .models import NL2SQLResult

__all__ = ["NL2SQLResult"]
