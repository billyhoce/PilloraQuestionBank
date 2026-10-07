"""The route stage, and ``ingest``: segment, split, then send each section on.

A split section goes to whichever pipeline can crop its shape:

* a **question** section -> the question extractor;
* an **answer** section whose template is ``annotated_booklet`` -> the same
  extractor, because each page carries the question and its answer together,
  which is the shape that pipeline was built for;
* an answer section whose template is ``table`` -> the table extractor
  (``question_extractor --table``), with the section's column layout
  (``question_columns``, ``reading_order``) as its hint. A scanned table is
  routed too: the table extractor straightens it, reads its rules off the
  pixels and its question numbers by OCR;
* an answer section with no template (the segmenter was unsure) -> nowhere,
  flagged for review, since guessing a pipeline would crop it as the wrong shape;
* a question or ``annotated_booklet`` section none of whose pages carries
  extractable text -> nowhere. That is a scan, which the question extractor
  cannot crop: it would emit every page "for review", which reads as a result
  when it is not one. Text is read through :mod:`question_extractor.geometry`,
  the only module that talks to PyMuPDF extraction. A section with *some* text
  pages is routed; the extractor already flags a textless page inside an
  otherwise digital paper.

A routed section lands in ``output/<paper>/<label>/`` -- the extractor's own
folder layout, because the split PDF is named for its label -- with the split's
page map as provenance, so every page in its manifest also carries its
``original_page``. Each section folder is replaced on every run, so a label that
stops being routed does not leave last run's rectangles behind.

``output/<paper>/ingest.json`` is the paper-level report: every section with its
label, range, template, route, status, question count, warnings and review
flag, plus the segment and split stages' own warnings. It is what a human opens
to see whether a paper ingested properly. One section failing is recorded there
and the rest still run.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from question_extractor import ExtractConfig, TableLayout, extract_paper, extract_table_paper
from question_extractor.geometry import extract_document
from question_extractor.pipeline import paper_name
from question_extractor.warnscope import collect_warnings

from .config import IngestConfig
from .segmenter import segment_paper
from .segments import Segment, SegmentPlan
from .splitter import Section, SplitResult, split_paper

log = logging.getLogger(__name__)

REPORT_NAME = "ingest.json"

QUESTION_EXTRACTOR = "question_extractor"
TABLE_EXTRACTOR = "question_extractor --table"

EXTRACTED = "extracted"
NOT_ROUTED = "not_routed"
FAILED = "failed"


@dataclass(frozen=True)
class Route:
    """Where a section goes: a pipeline name, or ``None`` with the reason why not."""

    pipeline: str | None
    reason: str = ""
    needs_review: bool = False


def choose_route(section: Section) -> Route:
    """The pipeline for a section by its kind and template, before reading its pages."""
    segment = section.segment
    if segment.kind == "question":
        return Route(QUESTION_EXTRACTOR)
    if segment.template == "annotated_booklet":
        return Route(QUESTION_EXTRACTOR)
    if segment.template == "table":
        return Route(TABLE_EXTRACTOR)
    return Route(
        None,
        "answer section has no template, so its shape is unknown",
        needs_review=True,
    )


@dataclass(frozen=True)
class SectionReport:
    label: str
    kind: str
    template: str | None
    first_page: int
    last_page: int
    route: str | None
    status: str
    reason: str = ""
    output: str | None = None
    questions: int = 0
    warnings: tuple[str, ...] = ()
    needs_review: bool = False
    review_pages: tuple[int, ...] = ()  # original-PDF pages

    def entry(self) -> dict:
        return {
            "label": self.label,
            "kind": self.kind,
            "template": self.template,
            "first_page": self.first_page,
            "last_page": self.last_page,
            "route": self.route,
            "status": self.status,
            "reason": self.reason,
            "output": self.output,
            "questions": self.questions,
            "warnings": list(self.warnings),
            "needs_review": self.needs_review,
            "review_pages": list(self.review_pages),
        }


@dataclass(frozen=True)
class IngestResult:
    pdf: Path
    paper: str
    plan: SegmentPlan
    split: SplitResult
    sections: tuple[SectionReport, ...] = ()
    warnings: tuple[str, ...] = ()  # the route stage's own
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def needs_review(self) -> bool:
        return (
            not self.plan.segmented
            or bool(self.split.skipped)
            or any(section.needs_review for section in self.sections)
        )

    def entry(self) -> dict:
        return {
            "pdf": Path(self.pdf).as_posix(),
            "paper": self.paper,
            "generated_at": self.generated_at,
            "segmented": self.plan.segmented,
            "needs_review": self.needs_review,
            "sections": [section.entry() for section in self.sections],
            "split_skipped": list(self.split.skipped),
            "segment_warnings": list(self.plan.warnings),
            "split_warnings": list(self.split.warnings),
            "warnings": list(self.warnings),
        }


def ingest_paper(
    pdf: Path,
    output_dir: Path,
    ingest_config: IngestConfig | None = None,
    extract_config: ExtractConfig | None = None,
    *,
    force: bool = False,
    debug: bool = False,
    review: bool = False,
) -> IngestResult:
    """Segment, split and route one PDF; write ``ingest.json`` either way."""
    extract_config = extract_config or ExtractConfig()
    plan = segment_paper(pdf, output_dir, ingest_config, force=force)
    split = split_paper(pdf, output_dir)
    paper_dir = output_dir / paper_name(pdf)

    with collect_warnings() as warnings:
        sections = tuple(
            route_section(section, paper_dir, extract_config, debug=debug, review=review)
            for section in split.sections
        )

    result = IngestResult(
        pdf=pdf,
        paper=paper_name(pdf),
        plan=plan,
        split=split,
        sections=sections,
        warnings=tuple(warnings),
    )
    paper_dir.mkdir(parents=True, exist_ok=True)
    path = paper_dir / REPORT_NAME
    path.write_text(json.dumps(result.entry(), indent=2) + "\n", encoding="utf-8")
    log.info("%s: report -> %s", result.paper, path)
    return result


def route_section(
    section: Section,
    paper_dir: Path,
    config: ExtractConfig,
    *,
    debug: bool = False,
    review: bool = False,
) -> SectionReport:
    """Send one section to its pipeline and record what came out; never raises."""
    segment = section.segment
    paper = paper_dir.name
    base = dict(
        label=segment.label,
        kind=segment.kind,
        template=segment.template,
        first_page=segment.first_page,
        last_page=segment.last_page,
    )

    out_dir = paper_dir / segment.label
    if out_dir.exists():
        try:
            shutil.rmtree(out_dir)
        except OSError as exc:
            log.warning(
                "%s: '%s' could not clear its previous output %s (%s)",
                paper,
                segment.label,
                out_dir,
                exc,
            )

    route = choose_route(section)
    if route.pipeline is None:
        if route.needs_review:
            log.warning("%s: '%s' not routed: %s", paper, segment.label, route.reason)
        return SectionReport(
            **base,
            route=None,
            status=NOT_ROUTED,
            reason=route.reason,
            needs_review=route.needs_review or segment.needs_review,
        )

    if route.pipeline == QUESTION_EXTRACTOR:
        try:
            has_text = _has_text(section.pdf)
        except Exception as exc:
            log.warning("%s: '%s' could not be read (%s)", paper, segment.label, exc)
            return SectionReport(
                **base, route=route.pipeline, status=FAILED, reason=str(exc), needs_review=True
            )
        if not has_text:
            reason = "no page carries extractable text (a scanned paper needs OCR)"
            log.warning("%s: '%s' not routed: %s", paper, segment.label, reason)
            return SectionReport(
                **base, route=None, status=NOT_ROUTED, reason=reason, needs_review=True
            )

    try:
        if route.pipeline == TABLE_EXTRACTOR:
            result = extract_table_paper(
                section.pdf,
                paper_dir,
                config,
                debug=debug,
                review=review,
                provenance=section.provenance,
                layout=_layout(segment),
            )
        else:
            result = extract_paper(
                section.pdf,
                paper_dir,
                config,
                debug=debug,
                review=review,
                provenance=section.provenance,
            )
    except Exception as exc:
        log.warning("%s: '%s' failed in %s (%s)", paper, segment.label, route.pipeline, exc)
        return SectionReport(
            **base, route=route.pipeline, status=FAILED, reason=str(exc), needs_review=True
        )

    review_pages = tuple(
        section.provenance.original_page(page.page)
        for page in result.pages
        if page.needs_review
    )
    return SectionReport(
        **base,
        route=route.pipeline,
        status=EXTRACTED,
        output=result.out_dir.relative_to(paper_dir).as_posix(),
        questions=len(result.questions),
        warnings=tuple(result.warnings),
        needs_review=result.needs_review or segment.needs_review,
        review_pages=review_pages,
    )


def _layout(segment: Segment) -> TableLayout | None:
    """The segment's column layout as the table extractor's hint; ``None`` when
    the segmenter gave none, and the extractor then measures."""
    if not segment.question_columns and segment.reading_order is None:
        return None
    return TableLayout(tuple(segment.question_columns), segment.reading_order)


def _has_text(pdf: Path) -> bool:
    with pymupdf.open(pdf) as doc:
        return any(page.has_text for page in extract_document(doc))
