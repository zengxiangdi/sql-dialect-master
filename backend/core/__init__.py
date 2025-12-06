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

__all__ = [
    # Configuration
    "setup_logging",
    "SUPPORTED_DIALECTS",
    "DIALECT_METADATA",
    "settings",
    "AppSettings",
    "get_dialect_ui_info",
    "get_dialect_api_info",
    "get_dialect_label",
    # Parser
    "SQLParser",
    "ParseResult",
    # Transpiler
    "SQLTranspiler",
    "TranspileResult",
    # Cache
    "TTLCache",
    # Post-processor
    "PostProcessor",
    # Function Encyclopedia
    "FunctionEncyclopedia",
    # Type Mapper
    "TypeMapper",
    # NL2SQL
    "NL2SQLGenerator",
    "NL2SQLResult",
    # Exceptions
    "SDMException",
    "UnsupportedDialectError",
    "TranspileError",
    "ParseError",
    "SecurityViolationError",
    "ValidationError",
]
