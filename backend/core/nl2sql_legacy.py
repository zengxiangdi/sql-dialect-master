#!/usr/bin/env python3
"""NL2SQL legacy module — P8 import-compatibility shim.

All implementation has moved to ``backend.core.nl2sql_pipeline``.  This
module is a thin re-export shim kept so existing import sites
(``from backend.core.nl2sql_legacy import NL2SQLGenerator`` /
``NL2SQLResult``) continue to work unchanged.  It is NOT deleted;
deletion happens in a future phase once every import/call site is
confirmed migrated.

``NL2SQLResult`` is re-exported from the single canonical source
(``nl2sql_pipeline.models``) so
``from backend.core.nl2sql import NL2SQLResult as A`` and
``from backend.core.nl2sql_legacy import NL2SQLResult as B`` satisfy
``A is B``.
"""
from .nl2sql_pipeline.models import NL2SQLResult
from .nl2sql_pipeline.orchestrator import (
    PipelineNL2SQLGenerator as NL2SQLGenerator,
)

__all__ = ["NL2SQLGenerator", "NL2SQLResult"]
