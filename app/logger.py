import logging
import os
import time
from logging.handlers import RotatingFileHandler

os.makedirs("logs", exist_ok=True)

log = logging.getLogger("pillora")
log.setLevel(logging.INFO)

_handler = RotatingFileHandler(
    "logs/app.log",
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8",
)
_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
log.addHandler(_handler)


class Timer:
    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed = time.perf_counter() - self._start

    @property
    def s(self) -> str:
        return f"{self.elapsed:.3f}s"


_SONNET_46_PRICES = {
    "input": 3.00,
    "cache_write": 3.75,
    "cache_hit": 0.30,
    "output": 15.00,
}


def log_tokens(func: str, model: str, usage) -> None:
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    ch = getattr(usage, "cache_read_input_tokens", 0) or 0

    token_str = f"in={inp} out={out}"
    if cw:
        token_str += f" cache_write={cw}"
    if ch:
        token_str += f" cache_hit={ch}"

    if model == "claude-sonnet-4-6":
        cost = (
            inp * _SONNET_46_PRICES["input"]
            + cw * _SONNET_46_PRICES["cache_write"]
            + ch * _SONNET_46_PRICES["cache_hit"]
            + out * _SONNET_46_PRICES["output"]
        ) / 1_000_000
        token_str += f" cost=${cost:.6f}"

    log.info(f"{func:<22}| tokens  | {token_str}")
