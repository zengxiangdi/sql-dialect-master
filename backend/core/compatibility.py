"""Explicit compatibility patch installation for legacy hardening adapters.

The project still contains legacy patches that are being migrated into the
canonical core classes. This module makes their activation order explicit and
idempotent instead of relying on scattered import-time side effects in
``backend.core.__init__``.
"""

from importlib import import_module

_PATCH_MODULES = (
    "batch_validation",
    "input_validation",
    "nl2sql_null_predicate_fix",
    "nl2sql_comparison_precedence_fix",
    "final_hardening",
    "audit_hardening",
    "production_hardening",
)

_installed = False


def install_compatibility_patches() -> None:
    """Install all remaining legacy compatibility adapters exactly once."""
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
        import_module(f".\{module_name}", package=__package__)

    _installed = True


__all__ = ["install_compatibility_patches"]
