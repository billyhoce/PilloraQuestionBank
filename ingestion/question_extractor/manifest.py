"""``manifest.json`` — the machine-readable record of one paper's extraction.

The manifest records, per question, the pages it occupies, the images it appears
in, and the crop rectangles **in PDF points**. Those rectangles are the real
output of the pipeline; the annotated PNGs are a view of them. Anything the tool
was unsure about is recorded too, so a paper needing manual attention can be
found without re-reading the logs.

Every page number here is a page of the PDF that was processed. When the run was
given provenance (:mod:`question_extractor.provenance`) each of those numbers is
joined by the page it came from in the original document — ``original_page``
beside ``page``, ``original_pages`` beside ``pages`` — and a top-level
``provenance`` block names that document and carries the whole map. Those fields
are written **only** when provenance was supplied, so a run without it produces
the manifest this tool has always produced, key for key.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .boundaries import Band, PageResult, Question
from .calibration import Calibration
from .config import ExtractConfig
from .provenance import SourceProvenance

log = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"


def _origin(page: int, provenance: SourceProvenance | None) -> dict:
    """``original_page`` for one page reference, or nothing without provenance.

    Spread into an entry (``**_origin(page, provenance)``) immediately after its
    ``page``, which both reads well and keeps a provenance-less run's entries
    identical to what they were before provenance existed.
    """
    return {} if provenance is None else {"original_page": provenance.original_page(page)}


def _origins(pages: list[int], provenance: SourceProvenance | None) -> dict:
    """:func:`_origin` for an entry holding a list of pages."""
    return {} if provenance is None else {"original_pages": provenance.original_pages(pages)}


def _rect_entry(band: Band, provenance: SourceProvenance | None) -> dict:
    """One crop rectangle, rounded to a sane precision for a text file.

    ``partition_y0``/``partition_y1`` are the boundaries before trimming — where
    this question's share of the page began and ended. They are the values to
    check against a paper's printed divider rules, which the trimmed rectangle no
    longer reaches.

    The coordinates are in the processed PDF's points and stay that way whatever
    provenance says; only ``original_page`` relates them to the original
    document. That is enough as long as the caller carved its sections by copying
    pages, which keeps each page's box and therefore its coordinates — a router
    that re-imposed or scaled pages would need to transform these rectangles
    itself, and nothing here could detect it had.
    """
    partition = band.partition if band.partition is not None else band.rect
    return {
        "page": band.page,
        **_origin(band.page, provenance),
        "segment": band.segment,
        "x0": round(band.rect.x0, 2),
        "y0": round(band.rect.y0, 2),
        "x1": round(band.rect.x1, 2),
        "y1": round(band.rect.y1, 2),
        "partition_y0": round(partition.y0, 2),
        "partition_y1": round(partition.y1, 2),
        "trimmed": band.rect != partition,
        "is_continuation": band.is_continuation,
        "figure_extended": band.figure_extended,
        "grid_page": band.grid_page,
        "pixel_ink": band.pixel_ink,
    }


def config_snapshot(config: ExtractConfig) -> dict:
    """The thresholds a run used, so its output can be reproduced or explained."""
    return asdict(config)


def build_manifest(
    paper: str,
    source_pdf: Path,
    page_count: int,
    start_page: int,
    end_page: int | None,
    questions: list[Question],
    results: list[PageResult],
    images: dict[int, str],
    calibration: Calibration | None,
    config: ExtractConfig,
    warnings: list[str],
    provenance: SourceProvenance | None = None,
) -> dict:
    """Assemble the manifest for one paper.

    ``source_pdf`` is always the PDF that was processed. ``provenance``, when
    given, names the document *that* was carved out of and is what every
    ``original_page`` is relative to; left out, not one provenance key is
    written.
    """
    return {
        "paper": paper,
        "source_pdf": str(source_pdf),
        **({} if provenance is None else {"provenance": provenance.manifest_entry()}),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "output_mode": "annotated_pages",
        "output_note": (
            "Pages are rendered whole with each question's crop rectangle drawn in red; "
            "no cropping is applied. The rectangles below are the crops that would be cut, "
            "trimmed onto each question's ink; partition_y0/partition_y1 give the "
            "untrimmed boundaries between one question and the next. A page "
            "recognised as graph paper is boxed across the full page width and the "
            "whole body band, and is not trimmed."
        ),
        "page_count": page_count,
        "start_page": start_page,
        # Last page of the paper proper; null when the paper prints no marker.
        "end_of_paper_page": end_page,
        "render_zoom": config.zoom,
        "calibration": (
            {
                "x_cut": round(calibration.x_cut, 2),
                "content_right": round(calibration.content_right, 2),
                "gutter_x": round(calibration.gutter_x, 2),
                "content_x": round(calibration.content_x, 2),
                "confident": calibration.confident,
            }
            if calibration is not None
            else None
        ),
        "questions": [
            {
                "question_number": question.number,
                "pages": question.pages,
                **_origins(question.pages, provenance),
                "images": [images[band.page] for band in question.bands if band.page in images],
                "rects": [_rect_entry(band, provenance) for band in question.bands],
            }
            for question in questions
        ],
        "pages": [
            {
                "page": result.page,
                **_origin(result.page, provenance),
                "image": images.get(result.page),
                "question_numbers": sorted({band.number for band in result.bands}),
                "anchors": [anchor.number for anchor in result.anchors],
                "continuation_note": result.continuation_note,
                "grid_page": result.grid is not None,
                "needs_review": result.needs_review,
                "review_reason": result.review_reason,
                "skip_reason": result.skip_reason,
            }
            for result in results
        ],
        "needs_review_pages": [
            {
                "page": result.page,
                **_origin(result.page, provenance),
                "reason": result.review_reason,
                "image": images.get(result.page),
            }
            for result in results
            if result.needs_review
        ],
        "skipped_pages": [
            {
                "page": result.page,
                **_origin(result.page, provenance),
                "reason": result.skip_reason,
                "image": images.get(result.page),
            }
            for result in results
            if result.skip_reason
        ],
        "warnings": warnings,
        "config": config_snapshot(config),
    }


def write_manifest(manifest: dict, out_dir: Path) -> Path:
    """Write ``manifest.json`` into a paper's output folder."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log.debug("wrote %s", path)
    return path
