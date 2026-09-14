"""Compatibility shim — intentionally empty.

Validation logic is now natively part of SQLTranspiler.
This module exists only to preserve import compatibility.
"""


def install_compatibility_patches() -> None:
    """No-op: all validation and conversion logic is now canonical."""
