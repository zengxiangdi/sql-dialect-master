"""Final API compatibility hardening patches for legacy endpoint behavior."""

from .main import ParseRequest, normalize_dialect

# Kept as a dedicated module so endpoint policy remains easy to audit. The
# endpoint itself is patched below after route registration by importing this
# module from main.py at the end of module initialization.
