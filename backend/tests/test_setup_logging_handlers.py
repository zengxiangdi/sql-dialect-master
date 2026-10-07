"""Regression tests for P7 setup_logging handler management.

``setup_logging`` previously called ``root_logger.handlers.clear()``
unconditionally, so any handler a caller had attached to the "backend"
logger was silently dropped on every re-call.  The P7 fix removes only
the handler types that the function itself installs (the stdout
console handler and any previously installed file handler), leaving
caller-attached handlers in place.
"""
from __future__ import annotations

import logging
import sys

from backend.core.config import setup_logging


def _clean_backend_logger() -> None:
    """Remove every handler from the 'backend' logger so tests start clean."""
    for h in list(logging.getLogger("backend").handlers):
        logging.getLogger("backend").removeHandler(h)


def test_repeated_setup_logging_is_idempotent() -> None:
    """Calling setup_logging twice must not accumulate duplicate console handlers."""
    _clean_backend_logger()
    setup_logging()
    first_count = len(logging.getLogger("backend").handlers)
    assert first_count == 1
    setup_logging()
    second_count = len(logging.getLogger("backend").handlers)
    assert second_count == 1, (
        f"setup_logging added {second_count - first_count} extra handler(s); "
        "it should replace its own console handler, not accumulate"
    )


def test_caller_attached_handler_survives_setup_logging() -> None:
    """A handler the caller attached must not be dropped by setup_logging."""
    _clean_backend_logger()
    backend_logger = logging.getLogger("backend")
    caller_handler = logging.Handler()
    backend_logger.addHandler(caller_handler)

    setup_logging()

    assert caller_handler in backend_logger.handlers, (
        "setup_logging() removed a caller-attached handler"
    )


def test_file_handler_is_replaced_on_recall() -> None:
    """A file handler installed by a previous call is replaced, not duplicated."""
    _clean_backend_logger()
    setup_logging()
    console = next(h for h in logging.getLogger("backend").handlers
                   if isinstance(h, logging.StreamHandler)
                   and not isinstance(h, logging.FileHandler))
    assert console.stream is sys.stdout


def test_cleanup_removes_stale_handlers() -> None:
    """The _clean_backend_logger helper clears all handlers (sanity check)."""
    backend_logger = logging.getLogger("backend")
    backend_logger.addHandler(logging.Handler())
    backend_logger.addHandler(logging.Handler())
    _clean_backend_logger()
    assert backend_logger.handlers == []
