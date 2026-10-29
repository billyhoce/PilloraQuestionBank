"""One shared collector turning logged warnings into an output file's ``warnings``.

Every stage (extractor, table extractor, segmenter, splitter, router, the pipeline's own) reports a
problem with ``log.warning`` and lists it in its output file. This module is the
only place that bridges the two: one logging handler, installed once on the
package loggers (``question_extractor``, ``ingester`` and ``pipeline``), appends each
WARNING-and-above message to the innermost open :func:`collect_warnings` scope.

The open scopes live in a context variable, not in a module-level list or a
collector handed down through arguments, for three reasons. A scope can wrap any
call without that call knowing about it, so a function never takes a collector
parameter. A context variable is per thread and per asyncio task, so concurrent
papers (the stage runner's tasks) cannot see each other's warnings, and a scope
is restored on exit even when the body raises, so a failed paper leaves nothing
behind for the next one in a folder run. And scopes nest: a warning goes only to
the innermost open scope, so what an extraction logs inside the router's scope
belongs to that extraction's manifest and does not also appear in the paper's
``ingest.json`` (ingest -> split -> extract each report their own), and never
reaches a scope that has already closed or belongs to another context.

The module lives in ``question_extractor`` because ``ingester`` already imports
that package; the reverse import would be a cycle.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

PACKAGE_LOGGERS = ("question_extractor", "ingester", "pipeline")

# The lists of the scopes open in this context, outermost first (only the last
# receives). A tuple, replaced rather than mutated, so a copied context never
# shares the stack itself.
_scopes: ContextVar[tuple[list[str], ...]] = ContextVar("warning_scopes", default=())


class _ScopeHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        scopes = _scopes.get()
        if scopes:
            scopes[-1].append(record.getMessage())


def _install() -> None:
    handler = _ScopeHandler()
    for name in PACKAGE_LOGGERS:
        logging.getLogger(name).addHandler(handler)


_install()


@contextmanager
def collect_warnings() -> Iterator[list[str]]:
    """Open a scope; yields the list its warnings are appended to as they are logged."""
    messages: list[str] = []
    token = _scopes.set((*_scopes.get(), messages))
    try:
        yield messages
    finally:
        _scopes.reset(token)


def current_warnings() -> list[str]:
    """A copy of the innermost open scope's warnings so far (empty outside any scope)."""
    scopes = _scopes.get()
    return list(scopes[-1]) if scopes else []
