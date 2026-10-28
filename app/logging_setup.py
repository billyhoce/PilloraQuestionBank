"""One log setup for the API and the worker: one human-readable line per record on stdout.

    2026-10-28 15:36:11.769 WARNING [job 139b2f78-… q1 locate] page 9: ignoring …
    2026-10-28 15:36:21.368 INFO    [req 4f1c… user 3] proposal saved

The bracket is the log context (``app/log_context.py``): job, section, stage and attempt inside a
worker task, request id and user inside an API request; a message never repeats it. Extra
``fields`` follow the message as ``key=value``. A multi-line record (a traceback) repeats the line
head on every line, so ``journalctl -t pillora-worker -o cat | grep <job id>`` still finds all of
it (see docs/DEPLOYMENT.md, Reading the logs). Called from ``app/main.py`` and
``app/worker/main.py``; idempotent.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime

from question_extractor.logcontext import describe

from app.log_context import ContextFilter

# Libraries that log every request at INFO ("HTTP Request: POST …", "Found credentials …"): our own
# lines already say what each call was for, so only their warnings are kept.
QUIET_LOGGERS = ("botocore", "boto3", "s3transfer", "urllib3", "httpx", "httpx2", "httpcore", "anthropic")


def _value(v) -> str:
    if isinstance(v, str) and v and not any(c.isspace() for c in v):
        return v
    return json.dumps(v, default=str, ensure_ascii=False)


def context_label(record: logging.LogRecord) -> str:
    """The bracketed line prefix: the task context, then the API request's id and user."""
    parts = [describe({k: getattr(record, k, None) for k in ("job_id", "section", "stage", "task_attempt")})]
    if getattr(record, "request_id", None):
        parts.append(f"req {record.request_id}")
    if getattr(record, "user_id", None) is not None:
        parts.append(f"user {record.user_id}")
    label = " ".join(p for p in parts if p)
    return f"[{label}] " if label else ""


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%d %H:%M:%S")
        head = f"{ts}.{int(record.msecs):03d} {record.levelname:<7} {context_label(record)}"
        text = record.getMessage()
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            text += "".join(f" {k}={_value(v)}" for k, v in fields.items() if v is not None)
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        first, *rest = text.splitlines() or [""]
        return "\n".join([head + first, *(f"{head}| {line}" for line in rest)])


_handler: logging.Handler | None = None


def configure_logging(level: str | None = None) -> None:
    global _handler
    root = logging.getLogger()
    root.setLevel((level or os.environ.get("LOG_LEVEL") or "INFO").upper())
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if _handler is not None and _handler in root.handlers:
        return
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(TextFormatter())
    _handler.addFilter(ContextFilter())
    root.addHandler(_handler)
