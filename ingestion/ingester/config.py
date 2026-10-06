"""Tunable knobs for the ingester. See ingester/README.md."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestConfig:
    # --- model choice -----------------------------------------------------
    model: str = "claude-haiku-4-5"
    retry_model: str = "claude-opus-5"
    # A plan is well under 500 tokens; a truncated reply loses the whole JSON.
    max_tokens: int = 8000
    # For legacy-thinking models. Must be >= 1024 and < max_tokens; 0 disables.
    thinking_budget_tokens: int = 4000
    # For adaptive-thinking models.
    effort: str = "high"
    # Models that take `budget_tokens` thinking and reject `effort`; any other
    # model gets adaptive thinking. Each shape is a 400 on the wrong model.
    legacy_thinking_prefixes: tuple[str, ...] = (
        "claude-haiku-",
        "claude-3",
        "claude-sonnet-4-5",
        "claude-opus-4-5",
        "claude-opus-4-1",
    )

    # --- document limits (API facts, not preferences) ---------------------
    # Base64 PDF page cap for a 200K-context model. Booklets run to ~80 pages.
    page_cap: int = 100
    max_request_bytes: int = 32 * 1024 * 1024
    # Reserved for the prompt, schema and envelope (a few KB in practice).
    request_overhead_bytes: int = 64 * 1024

    # --- validation -------------------------------------------------------
    # Booklets hold at most ~4 papers; a larger index is a hallucination.
    max_segment_index: int = 20
    # Question-number columns one table section may name. Every sample key prints
    # one column group (Bedok, Yuying, Clementi, the scanned key) or two side by
    # side (FMS, CCHMS, Nan Hua WA1); a third would not fit an A4 page.
    max_question_columns: int = 2
