import logging
import time

log = logging.getLogger("pillora")


def log_event(func: str, step: str, level: int = logging.INFO, **fields) -> None:
    """One structured line: ``msg`` is ``func/step`` and the fields ride as JSON keys."""
    log.log(level, "%s/%s", func, step, extra={"fields": {"func": func, "step": step, **fields}})


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


def log_tokens(func: str, model: str, usage) -> None:
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

    log_event(func, "tokens", **fields)
