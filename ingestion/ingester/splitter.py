"""The split stage: one ``segments.json`` in, one PDF per section out.

Each section's pages are copied whole into ``_split/<label>.pdf`` under the
paper's output folder, and ``_split/split.json`` records, per section, the page
map from each split page back to the original -- the map
:class:`question_extractor.SourceProvenance` takes. The work directory is
replaced on every run. See ingester/README.md.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from question_extractor import SourceProvenance
from question_extractor.pipeline import paper_name
from question_extractor.warnscope import collect_warnings

from .segmenter import find_plan
from .segments import Segment

log = logging.getLogger(__name__)

SPLIT_DIR = "_split"
SPLIT_NAME = "split.json"


@dataclass(frozen=True)
class Section:
    """A section written to its own PDF; ``page_map`` is split page -> original page."""

    segment: Segment
    pdf: Path
    original_pdf: Path
    page_map: dict[int, int]

    @property
    def provenance(self) -> SourceProvenance:
        return SourceProvenance(self.original_pdf, self.page_map)

    def entry(self) -> dict:
        return {
            "label": self.segment.label,
            "kind": self.segment.kind,
            "template": self.segment.template,
            "needs_review": self.segment.needs_review,
            "file": self.pdf.name,
            "first_page": self.segment.first_page,
            "last_page": self.segment.last_page,
            "page_map": {str(page): origin for page, origin in self.page_map.items()},
        }


@dataclass(frozen=True)
class SplitResult:
    pdf: Path
    paper: str
    work_dir: Path
    sections: tuple[Section, ...] = ()
    skipped: tuple[str, ...] = ()  # labels of sections that could not be written
    warnings: tuple[str, ...] = ()

    def entry(self) -> dict:
        return {
            "pdf": Path(self.pdf).as_posix(),
            "paper": self.paper,
            "sections": [section.entry() for section in self.sections],
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
        }


def split_paper(pdf: Path, output_dir: Path) -> SplitResult:
    work_dir = output_dir / paper_name(pdf) / SPLIT_DIR
    with collect_warnings() as warnings:
        sections, skipped, replaced = _split(pdf, output_dir, work_dir)

    result = SplitResult(
        pdf=pdf,
        paper=paper_name(pdf),
        work_dir=work_dir,
        sections=tuple(sections),
        skipped=tuple(skipped),
        warnings=tuple(warnings),
    )
    if replaced:
        path = work_dir / SPLIT_NAME
        path.write_text(json.dumps(result.entry(), indent=2) + "\n", encoding="utf-8")
        log.info("%s: %d section PDF(s) -> %s", result.paper, len(sections), work_dir)
    return result


def _split(
    pdf: Path, output_dir: Path, work_dir: Path
) -> tuple[list[Section], list[str], bool]:
    paper = paper_name(pdf)
    try:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)
    except OSError as exc:
        log.warning("%s: cannot replace the work directory %s (%s)", paper, work_dir, exc)
        return [], [], False

    plan = find_plan(pdf, output_dir / paper)
    if plan is None:
        log.warning("%s: no segments.json; run `segment` first; nothing was split", paper)
        return [], [], True
    if not plan.segmented:
        log.warning("%s: segments.json has no sections; nothing was split", paper)
        return [], [], True

    try:
        source = pymupdf.open(pdf)
    except Exception as exc:
        log.warning("%s: cannot be opened as a PDF (%s); nothing was split", paper, exc)
        return [], [segment.label for segment in plan.segments], True

    sections: list[Section] = []
    skipped: list[str] = []
    with source:
        for segment in plan.segments:
            section = _write_section(source, pdf, segment, work_dir, paper)
            if section is None:
                skipped.append(segment.label)
            else:
                sections.append(section)
    return sections, skipped, True


def _write_section(
    source: pymupdf.Document, pdf: Path, segment: Segment, work_dir: Path, paper: str
) -> Section | None:
    if not 1 <= segment.first_page <= segment.last_page <= source.page_count:
        log.warning(
            "%s: '%s' (pages %d-%d) is not within the PDF's %d page(s); skipped",
            paper,
            segment.label,
            segment.first_page,
            segment.last_page,
            source.page_count,
        )
        return None

    target = work_dir / f"{segment.label}.pdf"
    try:
        with pymupdf.open() as split:
            split.insert_pdf(
                source, from_page=segment.first_page - 1, to_page=segment.last_page - 1
            )
            split.save(target)
    except Exception as exc:
        log.warning("%s: '%s' could not be written (%s); skipped", paper, segment.label, exc)
        target.unlink(missing_ok=True)
        return None

    page_map = {position: page for position, page in enumerate(segment.pages, 1)}
    return Section(segment=segment, pdf=target, original_pdf=pdf, page_map=page_map)
