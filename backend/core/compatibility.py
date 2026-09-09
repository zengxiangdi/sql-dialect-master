"""Explicit compatibility installation for remaining legacy hardening adapters."""

from importlib import import_module
import re

from .config import DANGEROUS_SQL_PATTERNS, settings
from .p1_sql_scanner import mask_non_executable

_PATCH_MODULES = (
    "batch_validation",
    "input_validation",
    "nl2sql_null_predicate_fix",
    "nl2sql_comparison_precedence_fix",
    "final_hardening",
    "audit_hardening",
    "production_hardening",
    "p1_hardening",
)

_DANGEROUS_OPERATION_PATTERN = re.compile(
    r"\b(?:DROP|TRUNCATE|ALTER|CREATE|INSERT|UPDATE|DELETE)\b",
    re.IGNORECASE,
)
_STACKED_STATEMENT_PATTERN = re.compile(r";\s*[^;\s]", re.IGNORECASE)

_installed = False


def install_compatibility_patches() -> None:
    """Install compatibility adapters once, in their required order."""
    global _installed
    if _installed:
        return

    from .nl2sql import NL2SQLGenerator
    from .nl2sql_components.boolean_conditions import extract_boolean_conditions

    if not getattr(NL2SQLGenerator, "_sdm_boolean_patch_installed", False):
        original_extract = NL2SQLGenerator._extract_conditions_enhanced

        def extract_conditions_with_boolean(self, text, original):
            boolean_conditions = extract_boolean_conditions(text)
            if boolean_conditions:
                return boolean_conditions
            return original_extract(self, text, original)

        NL2SQLGenerator._extract_conditions_enhanced = extract_conditions_with_boolean
        NL2SQLGenerator._sdm_boolean_patch_installed = True

    for module_name in _PATCH_MODULES:
        import_module(f".{module_name}", package=__package__)

    from .function_call_scanner import replace_function_calls
    from .post_processor import PostProcessor
    from .transpiler import SQLTranspiler

    if not getattr(PostProcessor, "_sdm_function_scanner_installed", False):
        PostProcessor._replace_function_calls = staticmethod(replace_function_calls)
        PostProcessor._sdm_function_scanner_installed = True

    if not getattr(SQLTranspiler, "_sdm_default_security_patch_installed", False):
        original_validate_security = SQLTranspiler._validate_security

        def validate_security_with_default_dangerous_block(self, sql):
            result = original_validate_security(self, sql)
            executable_sql = mask_non_executable(sql)
            has_stacked_statements = bool(_STACKED_STATEMENT_PATTERN.search(executable_sql))
            has_known_danger = any(pattern.search(executable_sql) for pattern, _ in DANGEROUS_SQL_PATTERNS)

            # Let the dedicated stacked-statement adapter own the explicit
            # transpiler-boundary rejection; direct security validation still
            # reports real stacked SQL as a security violation.
            if result.get("reason") == "Multiple SQL statements detected":
                if has_stacked_statements:
                    return result
                result["blocked"] = False
                result["reason"] = None
                result["warnings"] = []
                return result

            # If the legacy adapter blocked text that only occurs inside a
            # string/comment/dollar-quote/q-quote, normalize it back to safe.
            if result.get("blocked") and not has_known_danger and not has_stacked_statements:
                result["blocked"] = False
                result["reason"] = None
                result["warnings"] = []

            if settings.security_block_dangerous and _DANGEROUS_OPERATION_PATTERN.search(executable_sql):
                result["blocked"] = True
                result["reason"] = "Dangerous SQL operation detected"
            return result

        SQLTranspiler._validate_security = validate_security_with_default_dangerous_block
        SQLTranspiler._sdm_default_security_patch_installed = True

    _installed = True


__all__ = ["install_compatibility_patches"]
