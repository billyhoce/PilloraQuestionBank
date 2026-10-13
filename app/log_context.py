"""Copies the logging context (see ``question_extractor.logcontext``) onto every log record."""

import logging

from question_extractor.logcontext import current_context, log_context, set_context

__all__ = ["ContextFilter", "log_context", "set_context", "FIELDS"]

FIELDS = ("job_id", "section", "stage", "task_attempt", "request_id", "user_id")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = current_context()
        for name in FIELDS:
            if getattr(record, name, None) is None:
                setattr(record, name, ctx.get(name))
        return True
