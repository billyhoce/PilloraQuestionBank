"""The routing rules: which pipeline can crop a section, and the report row it earns.

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

:func:`choose_route`, :func:`has_text` and :func:`table_layout` are what the
``pipeline`` stages call (the fan-out chooses each section's chain with
``choose_route``; ``locate`` applies the text rule; ``questions`` reads the table
layout). The walk over a paper's sections that used to live here, ``ingest``, is
``pipeline``'s ``report`` stage: it writes ``<paper>/ingest.json`` -- every section
with its label, range, template, route, status, question count, warnings and review
flag, as a :class:`SectionReport` -- from the artefacts the stages left.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from question_extractor import TableLayout
from question_extractor.geometry import extract_document

from .segments import Segment
from .splitter import Section

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


def table_layout(segment: Segment) -> TableLayout | None:
    """The segment's column layout as the table extractor's hint; ``None`` when
    the segmenter gave none, and the extractor then measures."""
    if not segment.question_columns and segment.reading_order is None:
        return None
    return TableLayout(tuple(segment.question_columns), segment.reading_order)


def has_text(pdf: Path) -> bool:
    """Whether any page of the PDF carries extractable text (``False`` for a scan)."""
    with pymupdf.open(pdf) as doc:
        return any(page.has_text for page in extract_document(doc))
