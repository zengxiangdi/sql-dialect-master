# SQL Dialect Master - Core Module
from .cache import TTLCache
from .config import (
    DIALECT_METADATA,
    SUPPORTED_DIALECTS,
    AppSettings,
    get_dialect_api_info,
    get_dialect_label,
    get_dialect_ui_info,
    settings,
    setup_logging,
)
from .exceptions import (
    ParseError,
    SDMException,
    SecurityViolationError,
    TranspileError,
    UnsupportedDialectError,
    ValidationError,
)
from .functions_lookup import FunctionEncyclopedia
from .nl2sql import NL2SQLGenerator, NL2SQLResult
from .parser import ParseResult, SQLParser
from .post_processor import PostProcessor
from .semantic_diff import SemanticDiff, SQLSemanticDiffer, diff_sql_ast
from .transpiler import SQLTranspiler, TranspileResult
from .type_mapping import TypeMapper

__all__ = [
    "DIALECT_METADATA",
    "SUPPORTED_DIALECTS",
    "AppSettings",
    "FunctionEncyclopedia",
    "NL2SQLGenerator",
    "NL2SQLResult",
    "ParseError",
    "ParseResult",
    "PostProcessor",
    "SDMException",
    "SQLParser",
    "SQLSemanticDiffer",
    "SQLTranspiler",
    "SecurityViolationError",
    "SemanticDiff",
    "TTLCache",
    "TranspileError",
    "TranspileResult",
    "TypeMapper",
    "UnsupportedDialectError",
    "ValidationError",
    "diff_sql_ast",
    "get_dialect_api_info",
    "get_dialect_label",
    "get_dialect_ui_info",
    "settings",
    "setup_logging",
]
