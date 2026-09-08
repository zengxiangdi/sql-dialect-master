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
from .semantic_ir import (
    And,
    BooleanExpression,
    ComparisonPredicate,
    Not,
    NullPredicate,
    Or,
    Predicate,
    RangePredicate,
    SemanticQuery,
    SetPredicate,
    TextPredicate,
)
from .semantic_parser import parse_condition_expression, parse_condition_list
from .semantic_integration import enrich_result_with_semantic_ir
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
    "Predicate",
    "ComparisonPredicate",
    "RangePredicate",
    "TextPredicate",
    "NullPredicate",
    "SetPredicate",
    "BooleanExpression",
    "And",
    "Or",
    "Not",
    "SemanticQuery",
    "parse_condition_expression",
    "parse_condition_list",
    "enrich_result_with_semantic_ir",
    "SDMException",
    "UnsupportedDialectError",
    "TranspileError",
    "ParseError",
    "SecurityViolationError",
    "ValidationError",
]
