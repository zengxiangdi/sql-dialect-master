"""Explicit compatibility installation for remaining legacy hardening adapters."""


def install_compatibility_patches() -> None:
    """Install remaining legacy compatibility adapters in deterministic order."""
    from .nl2sql import NL2SQLGenerator
    from .nl2sql_components.boolean_conditions import extract_boolean_conditions
    from .rules import TransformRule

    if not getattr(NL2SQLGenerator, "_sdm_boolean_patch_installed", False):
        original_extract = NL2SQLGenerator._extract_conditions_enhanced

        def extract_conditions_with_boolean(self, text, original):
            boolean_conditions = extract_boolean_conditions(text)
            if boolean_conditions:
                return boolean_conditions
            return original_extract(self, text, original)

        NL2SQLGenerator._extract_conditions_enhanced = extract_conditions_with_boolean
        NL2SQLGenerator._sdm_boolean_patch_installed = True


__all__ = ["install_compatibility_patches"]
