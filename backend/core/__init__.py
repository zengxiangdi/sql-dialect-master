# SQL Dialect Master - Core Module
from .config import (
    setup_logging,
    SUPPORTED_DIALECTS,
    DIALECT_METADATA,
    settings,
    AppSettings,
    get_dialect_ui_info,
    get_dialect_api_info,
    get_dialect_label,
)
from .parser import SQLParser, ParseResult
from .transpiler import SQLTranspiler, TranspileResult
from .semantic_diff import SQLSemanticDiffer, SemanticDiff, diff_sql_ast
from .post_processor import PostProcessor
from .functions_lookup import FunctionEncyclopedia
from .type_mapping import TypeMapper
from .nl2sql import NL2SQLGenerator, NL2SQLResult
from .cache import TTLCache
from .exceptions import (
    SDMException,
    UnsupportedDialectError,
    TranspileError,
    ParseError,
    SecurityViolationError,
    ValidationError,
)
from .compatibility import install_compatibility_patches
from .structured_aggregation import install_structured_aggregation_rules

# Legacy compatibility adapters are installed through one explicit, idempotent entry point.
install_compatibility_patches()
# Install the scanner-backed aggregation handlers after legacy patches so the
# structural rewrite contract remains the effective runtime implementation.
install_structured_aggregation_rules()

__all__ = [
    "setup_logging",
    "SUPPORTED_DIALECTS",
    "DIALECT_METADATA",
    "settings",
    "AppSettings",
    "get_dialect_ui_info",
    "get_dialect_api_info",
    "get_dialect_label",
    "SQLParser",
    "ParseResult",
    "SQLTranspiler",
    "TranspileResult",
    "SQLSemanticDiffer",
    "SemanticDiff",
    "diff_sql_ast",
    "TTLCache",
    "PostProcessor",
    "FunctionEncyclopedia",
    "TypeMapper",
    "NL2SQLGenerator",
    "NL2SQLResult",
    "SDMException",
    "UnsupportedDialectError",
    "TranspileError",
    "ParseError",
    "SecurityViolationError",
    "ValidationError",
    "install_compatibility_patches",
]
