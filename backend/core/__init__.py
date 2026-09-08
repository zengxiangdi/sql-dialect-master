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

# Install the focused multi-condition enhancement after NL2SQLGenerator is loaded.
from .nl2sql_components.boolean_conditions import extract_boolean_conditions

_original_extract_conditions = NL2SQLGenerator._extract_conditions_enhanced


def _extract_conditions_with_boolean(self, text, original):
    boolean_conditions = extract_boolean_conditions(text)
    if boolean_conditions:
        return boolean_conditions
    return _original_extract_conditions(self, text, original)


NL2SQLGenerator._extract_conditions_enhanced = _extract_conditions_with_boolean

# Install batch-size validation at the core boundary so oversized requests
# cannot be silently truncated by the legacy batch implementations.
from . import batch_validation  # noqa: F401,E402

# Install core input validation so invalid direct callers receive the same
# structured validation result as API callers.
from . import input_validation  # noqa: F401,E402

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
]
