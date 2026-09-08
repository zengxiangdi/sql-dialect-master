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

# Install the focused NULL-predicate precedence fix after NL2SQLGenerator is loaded.
from . import nl2sql_null_predicate_fix  # noqa: F401,E402

# Install the focused comparison precedence fix after the NULL-predicate fix.
from . import nl2sql_comparison_precedence_fix  # noqa: F401,E402

# Install the consolidated final hardening layer after all legacy compatibility patches.
from . import final_hardening  # noqa: F401,E402

# Install the audit boundary last: quote-aware rewrites, AST-first security,
# conservative ROWNUM conversion, and semantic warning guards.
from . import audit_hardening  # noqa: F401,E402

# Install second-pass production guards after all compatibility patches.
from . import production_hardening  # noqa: F401,E402

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
