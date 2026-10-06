"""The segmentation stage: one PDF in, one ``segments.json`` out.

Reuse a plan on disk, refuse an oversized document, ask, validate, escalate
once, write the file either way. See ingester/README.md.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

import pymupdf

from question_extractor.pipeline import paper_name

from .config import IngestConfig
from .request import ModelAnswer, ask, encode_pdf, encoded_size
from .segments import (
    SEGMENTS_NAME,
    Attempt,
    SegmentPlan,
    read_plan,
    write_plan,
    write_plan_to,
)
from .validation import anomalies, validate

log = logging.getLogger(__name__)

FIXTURE_SUFFIX = ".segments.json"


class _WarningCollector(logging.Handler):
    """Collects this package's warnings into ``segments.json``."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def fixture_path(pdf: Path) -> Path:
    """The committed plan for a paper: ``<paper>.segments.json`` beside its PDF."""
    return pdf.with_suffix(FIXTURE_SUFFIX)


def _mb(size_bytes: float) -> float:
    return size_bytes / (1024 * 1024)


def too_large_to_ask(
    page_count: int, pdf_bytes: int, config: IngestConfig
) -> str | None:
    """Why this document cannot be sent (naming the cap hit), or ``None``."""
    if page_count > config.page_cap:
        return (
            f"the document is {page_count} pages, past the {config.page_cap}-page "
            f"cap on a base64 PDF for {config.model}; it was not segmented"
        )

    encoded = encoded_size(pdf_bytes)
    budget = config.max_request_bytes - config.request_overhead_bytes
    if encoded > budget:
        return (
            f"the document is {_mb(pdf_bytes):.1f}MB, which is "
            f"{_mb(encoded):.1f}MB once base64-encoded and does not fit the API's "
            f"{_mb(config.max_request_bytes):.0f}MB request limit; it was not segmented"
        )
    return None


def segment_paper(
    pdf: Path,
    output_dir: Path,
    config: IngestConfig | None = None,
    *,
    force: bool = False,
    write_fixture: bool = False,
) -> SegmentPlan:
    config = config or IngestConfig()
    out_dir = output_dir / paper_name(pdf)

    if not force:
        reused = find_plan(pdf, out_dir)
        if reused is not None:
            return reused

    collector = _WarningCollector()
    package_log = logging.getLogger(__package__)
    package_log.addHandler(collector)
    try:
        plan = _segment(pdf, config, collector)
    finally:
        package_log.removeHandler(collector)

    path = write_plan(plan, out_dir)
    log.info(
        "%s: %d section(s) from %s -> %s",
        plan.paper,
        len(plan.segments),
        plan.model or "no model",
        path,
    )
    if write_fixture:
        fixture = write_plan_to(plan, fixture_path(pdf))
        log.info("%s: wrote fixture %s", plan.paper, fixture)
    return plan


def find_plan(pdf: Path, out_dir: Path) -> SegmentPlan | None:
    """The plan in ``out_dir``, else the committed fixture (copied there), else ``None``."""
    cached = out_dir / SEGMENTS_NAME
    if cached.exists():
        log.info("%s: reusing %s", paper_name(pdf), cached)
        return read_plan(cached, pdf=pdf)

    fixture = fixture_path(pdf)
    if fixture.exists():
        plan = read_plan(fixture, pdf=pdf)
        write_plan(plan, out_dir)
        log.info("%s: reusing fixture %s", plan.paper, fixture)
        return plan
    return None


def _segment(
    pdf: Path, config: IngestConfig, collector: _WarningCollector
) -> SegmentPlan:
    paper = paper_name(pdf)
    snapshot = asdict(config)

    try:
        with pymupdf.open(pdf) as document:
            page_count = document.page_count
    except Exception as exc:
        log.warning("%s: cannot be opened as a PDF (%s)", paper, exc)
        return SegmentPlan(
            pdf=pdf,
            paper=paper,
            page_count=0,
            warnings=tuple(collector.messages),
            config=snapshot,
        )

    refusal = too_large_to_ask(page_count, pdf.stat().st_size, config)
    if refusal is not None:
        log.warning("%s: %s", paper, refusal)
        return SegmentPlan(
            pdf=pdf,
            paper=paper,
            page_count=page_count,
            warnings=tuple(collector.messages),
            config=snapshot,
        )

    pdf_b64 = encode_pdf(pdf)
    attempts: list[Attempt] = []
    accepted: ModelAnswer | None = None

    for position, model in enumerate((config.model, config.retry_model), 1):
        answer = ask(model, pdf_b64, page_count, config)
        if answer.error is not None:
            log.warning("%s: %s could not answer: %s", paper, model, answer.error)
            attempts.append(Attempt(model=model, accepted=False, problems=(answer.error,)))
            continue

        problems = validate(answer.segments, page_count, config)
        if problems:
            for problem in problems:
                log.warning("%s: %s's answer is invalid: %s", paper, model, problem)
            attempts.append(
                Attempt(model=model, accepted=False, problems=tuple(problems))
            )
            continue

        attempts.append(Attempt(model=model, accepted=True))
        accepted = answer
        if position > 1:
            log.info("%s: accepted %s's answer after a retry", paper, model)
        break

    segments = accepted.segments if accepted is not None else ()
    if accepted is None:
        log.warning(
            "%s: no model produced a usable plan after %d attempt(s); it was not "
            "segmented",
            paper,
            len(attempts),
        )
    else:
        for note in anomalies(segments, page_count, config):
            log.warning("%s: %s", paper, note)

    return SegmentPlan(
        pdf=pdf,
        paper=paper,
        page_count=page_count,
        segments=segments,
        model=accepted.model if accepted is not None else None,
        attempts=tuple(attempts),
        warnings=tuple(collector.messages),
        config=snapshot,
    )
