"""Fields stamped onto every log record: the job, section, stage and attempt a line belongs to.

Next to :mod:`warnscope` for the same reason: ``ingester`` and ``pipeline`` already import this
package, and ``ingestion`` never imports ``app``. The stage runner opens a :func:`log_context`
around each claimed task; the webapp's logging filter (``app/log_context.py``) reads
:func:`current_context` and copies the fields onto each record. The context is a context
variable, so it is per thread and per asyncio task, restored on exit, and nests (inner fields
override outer ones).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType

_fields: ContextVar[Mapping[str, object]] = ContextVar("log_fields", default=MappingProxyType({}))


def current_context() -> Mapping[str, object]:
    """The fields of the innermost open context (empty outside any)."""
    return _fields.get()


def set_context(**fields: object) -> None:
    """Merge fields into the current context without a scope (for a request's own context)."""
    _fields.set({**_fields.get(), **{k: v for k, v in fields.items() if v is not None}})


@contextmanager
def log_context(**fields: object) -> Iterator[None]:
    """Stamp ``fields`` (``None`` values are skipped) on every record logged in the block."""
    token = _fields.set({**_fields.get(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _fields.reset(token)
