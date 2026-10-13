"""One log setup for the API and the worker: JSON lines on stdout from the root logger.

Docker's ``json-file`` driver keeps the history, so ``docker logs <container> | grep <job id>``
finds every line of a job from either container. Called from ``app/main.py`` and
``app/worker/main.py``; idempotent.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime

from app.log_context import ContextFilter



class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        out = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for name in ("job_id", "section", "stage", "request_id", "user_id"):
            out[name] = getattr(record, name, None)
        if getattr(record, "task_attempt", None) is not None:
            out["task_attempt"] = record.task_attempt
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            out.update({k: v for k, v in extra.items() if k not in out})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


_handler: logging.Handler | None = None


def configure_logging(level: str | None = None) -> None:
    global _handler
    root = logging.getLogger()
    root.setLevel((level or os.environ.get("LOG_LEVEL") or "INFO").upper())
    if _handler is not None and _handler in root.handlers:
        return
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(JsonFormatter())
    _handler.addFilter(ContextFilter())
    root.addHandler(_handler)
