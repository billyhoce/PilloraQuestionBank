import json
import logging
import time

from app.log_context import log_context

log = logging.getLogger("pillora")


def log_event(message: str, level: int = logging.INFO, **fields) -> None:
    """One line: ``message`` for a human, then ``fields`` (``None`` ones left out) as ``key=value``."""
    log.log(level, "%s", message, extra={"fields": fields})


def log_job_event(job_id, message: str, level: int = logging.INFO, **fields) -> None:
    """A lifecycle event of an ingest job, logged under the job's context (its id leads the line)."""
    with log_context(job_id=str(job_id)):
        log_event(message, level, **fields)


class Timer:
    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed = time.perf_counter() - self._start

    @property
    def s(self) -> float:
        """Elapsed seconds, rounded to the millisecond (a number, for structured fields)."""
        return round(self.elapsed, 3)


# USD per million tokens. Cache writes bill at 1.25x input, cache reads at 0.1x.
_PRICES = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "cache_write": 3.75,
        "cache_hit": 0.30,
        "output": 15.00,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "cache_write": 1.25,
        "cache_hit": 0.10,
        "output": 5.00,
    },
    # The ingest worker's segment stage asks by alias (ingestion's IngestConfig.model),
    # the same model and price as the dated id above.
    "claude-haiku-4-5": {
        "input": 1.00,
        "cache_write": 1.25,
        "cache_hit": 0.10,
        "output": 5.00,
    },
    # IngestConfig.retry_model, asked once when claude-haiku-4-5's segment answer is invalid.
    "claude-opus-5": {
        "input": 5.00,
        "cache_write": 6.25,
        "cache_hit": 0.50,
        "output": 25.00,
    },
}


def usage_fields(model: str, usage) -> dict:
    """Token counts and dollar cost of one Claude call; the one place that applies ``_PRICES``."""
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    ch = getattr(usage, "cache_read_input_tokens", 0) or 0

    fields = {"model": model, "input_tokens": inp, "output_tokens": out}
    if cw:
        fields["cache_write"] = cw
    if ch:
        fields["cache_hit"] = ch

    prices = _PRICES.get(model)
    if prices:
        cost = (
            inp * prices["input"]
            + cw * prices["cache_write"]
            + ch * prices["cache_hit"]
            + out * prices["output"]
        ) / 1_000_000
        fields["cost_usd"] = round(cost, 6)
    return fields


# A logged reply is cut here: Docker splits a log line past 16 KB into separate journald
# entries, and a segment reply (the largest) is a few KB.
MAX_REPLY_CHARS = 12_000


def _compact(reply) -> str:
    """The reply on one line: JSON re-dumped compactly, other text with its newlines escaped."""
    if not isinstance(reply, str):
        return json.dumps(reply, default=str, ensure_ascii=False)
    try:
        return json.dumps(json.loads(reply), ensure_ascii=False)
    except ValueError:
        return reply.replace("\n", "\\n")


def log_claude_call(
    purpose: str, model: str, usage, request_id: str | None = None, reply=None,
    seconds: float | None = None, stop_reason: str | None = None,
) -> dict:
    """One line per Messages API call: what it was for, model, time, tokens, cost, Anthropic's
    request id and the reply (text, or a tool call's input). Returns :func:`usage_fields`."""
    fields = usage_fields(model, usage)
    said = f"Claude call ({purpose}): {model}"
    if seconds is not None:
        said += f", {seconds:.1f}s"
    said += f", {fields['input_tokens']:,} in"
    if fields.get("cache_hit"):
        said += f" (+{fields['cache_hit']:,} cached)"
    said += f" / {fields['output_tokens']:,} out tokens"
    if "cost_usd" in fields:
        said += f", ${fields['cost_usd']:.4f}"
    if isinstance(request_id, str):
        said += f", {request_id}"
    if isinstance(stop_reason, str) and stop_reason not in ("end_turn", "tool_use"):
        said += f", stopped on {stop_reason}"
    if reply is not None:
        text = _compact(reply)
        if len(text) > MAX_REPLY_CHARS:
            text = f"{text[:MAX_REPLY_CHARS]}… ({len(text) - MAX_REPLY_CHARS:,} more chars)"
        said += f". Reply: {text}"
    log.info("%s", said)
    return fields
