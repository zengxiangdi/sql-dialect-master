# SQL Dialect Master - Core Module
import os

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
from .compatibility import install_compatibility_patches

# Dangerous SQL is blocked by default at package runtime. Operators that need
# the previous compatibility behavior must opt out explicitly via environment.
if "SDM_SECURITY_BLOCK_DANGEROUS" not in os.environ:
    settings.security_block_dangerous = True

# Legacy compatibility adapters are installed through one explicit, idempotent entry point.
install_compatibility_patches()

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
