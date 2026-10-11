"""Stable fingerprints for invalidating result state after input changes."""
from __future__ import annotations

import hashlib


def input_fingerprint(*parts: object) -> str:
    """Return a process-independent digest for a collection of inputs.

    Length-prefixed encoding keeps boundaries unambiguous (``("ab", "c")``
    cannot collide with ``("a", "bc")``).  The values are intentionally
    treated as display/input data and converted to text rather than hashed via
    Python's salted ``hash``.
    """
    digest = hashlib.sha256()
    for part in parts:
        value = str(part)
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


__all__ = ["input_fingerprint"]
