"""Explicit compatibility installation for remaining legacy hardening adapters."""

from importlib import import_module

_PATCH_MODULES = (
    "batch_validation",
    "input_validation",
    "nl2sql_null_predicate_fix",
    "nl2sql_comparison_precedence_fix",
    "final_hardening",
    "audit_hardening",
    "production_hardening",
    "p1_hardening",
    "p2_data_validation",
    "p2_health_semantics",
    "p2_health_semantics_fix",
)

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

    _installed = True


__all__ = ["install_compatibility_patches"]
