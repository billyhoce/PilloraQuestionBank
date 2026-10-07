"""End-to-end extraction of one paper.

Order matters and each stage depends only on the ones above it:

1. **geometry** — text lines, image boxes, drawing boxes for every page.
2. **furniture** — running header/footer, giving each page its body band.
3. **start and end page** — the first page carrying a question number, which skips
   the cover and the formula sheet without needing them described, and the page
   printing the end-of-paper marker, past which an answer key or a second paper
   would otherwise be cropped as if it were part of this one.
4. **calibration** — ``x_cut`` and ``content_right`` from the question pages.
5. **boundaries** — anchors, snapped boundaries, cross-page grouping.
6. **trim** — each crop shrunk onto its own ink. Separate from stage 5 on purpose:
   it only makes rectangles smaller, so it cannot change which content belongs to
   which question, and turning it off reproduces stage 5's output exactly.
7. **render + manifest** — annotated pages and the record of the rectangles.

Stages 1-6 are :func:`locate_questions`, which writes nothing and returns a
:class:`LocatedPaper`; stage 7 is :func:`write_renders` and
:func:`write_question_manifest`, each taking that result. :func:`extract_paper`
is the three in sequence.

A caller may also hand in provenance: the document this PDF was carved out of
and the page map back into it (:mod:`question_extractor.provenance`). It takes
part in no stage above — detection reads only the PDF it was given — and is
consulted once, by the manifest, so each page number it records also names the
page it came from. Without it the run is exactly what it was before provenance
existed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .boundaries import PageResult, Question, build_questions
from .calibration import Calibration, CalibrationError, calibrate, find_question_pages
from .config import ExtractConfig
from .furniture import Furniture, detect_furniture
from .geometry import PageGeometry, extract_document
from .manifest import build_manifest, write_manifest
from .pagekind import end_of_paper_y
from .provenance import SourceProvenance, check_page_map
from .render import render_pages
from .trim import trim_bands
from .warnscope import collect_warnings, current_warnings

log = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """A paper could not be processed at all."""


@dataclass
class PaperResult:
    """What one paper's run produced."""

    paper: str
    out_dir: Path
    questions: list[Question]
    pages: list[PageResult]
    images: dict[int, str]
    manifest_path: Path
    warnings: list[str]
    # The document this PDF was carved out of, when the caller named one. Kept so
    # a caller handling many sections can pair a result with its source without
    # re-reading the manifest.
    provenance: SourceProvenance | None = None

    @property
    def needs_review(self) -> bool:
        return any(page.needs_review for page in self.pages)


def paper_name(pdf_path: Path) -> str:
    """Output folder name for a paper: its file stem, path separators removed."""
    return pdf_path.stem.replace("/", "_").strip() or "paper"


def resolve_start_page(
    question_pages: list[int], start_page: int | None, page_count: int
) -> int | None:
    """Decide which page the questions begin on, or ``None`` if none qualifies.

    An explicit ``--start-page`` always wins. Otherwise the first page holding a
    plausible question number is used: a cover page has no gutter numbers, and a
    formula sheet's leading tokens all sit in the content column, so both are
    skipped without being recognised as such.
    """
    if start_page is not None:
        if not 1 <= start_page <= page_count:
            raise ExtractionError(
                f"--start-page {start_page} is outside the document (1-{page_count})"
            )
        return start_page
    return question_pages[0] if question_pages else None


def end_paper_at_marker(
    pages: list[PageGeometry],
    furniture: Furniture,
    config: ExtractConfig,
    start_page: int,
) -> int | None:
    """Last page of the paper proper, the marker clipped out of its body band.

    A PDF is usually more than the question paper: 57 of the 111 sample papers
    print an end-of-paper marker, and behind it sit answer keys, second papers and
    full marking schemes — 364 crop rectangles' worth, all of them boxed as if they
    were questions of this paper.

    The marker is looked for only at or after the start page, so a cover sheet
    mentioning the end of the paper cannot truncate the document.

    Clipping the band is what does the work, because every later stage reads a page
    through :meth:`Furniture.body_lines`: with the marker outside the band it
    leaves calibration, the content intervals, the last question's bottom edge,
    blank-page detection and the trim's ink box in one move.
    """
    for geom in pages:
        if geom.number < start_page:
            continue
        marker_y = end_of_paper_y(furniture.body_lines(geom), config)
        if marker_y is None:
            continue
        furniture.clip_band(geom.number, marker_y - config.furniture_pad)
        log.info(
            "page %d carries an end-of-paper marker; the paper ends there", geom.number
        )
        return geom.number
    return None


def _unparsed_results(pages: list[PageGeometry], furniture) -> list[PageResult]:
    """Mark every page as needing review, for a paper no anchor was found in."""
    return [
        PageResult(
            page=geom.number,
            has_text=geom.has_text,
            needs_review=True,
            review_reason=(
                "no extractable text (possible scanned page)"
                if not geom.has_text
                else "no question number found in the gutter on any page"
            ),
            body_band=furniture.bands.get(geom.number),
        )
        for geom in pages
    ]


@dataclass
class LocatedPaper:
    """What :func:`locate_questions` found in one paper; nothing of it is on disk yet."""

    paper: str
    pdf_path: Path
    page_count: int
    questions: list[Question]
    pages: list[PageResult]
    calibration: Calibration | None
    start_page: int
    end_page: int | None


def locate_questions(
    pdf_path: Path,
    config: ExtractConfig,
    start_page: int | None = None,
    provenance: SourceProvenance | None = None,
) -> LocatedPaper:
    """Stages 1-6: find every question's rectangles. Writes nothing.

    The result is all the writers need: :func:`write_renders` draws the pages,
    :func:`write_question_manifest` records the rectangles. ``provenance`` is
    only checked here (one warning for a bad page map); it changes no detection.
    Warnings go to the innermost open :func:`collect_warnings` scope.
    """
    name = paper_name(pdf_path)
    log.info("processing %s", pdf_path.name)

    try:
        with pymupdf.open(pdf_path) as doc:
            page_count = doc.page_count
            pages = extract_document(doc)
    except Exception as exc:
        raise ExtractionError(f"could not open {pdf_path.name}: {exc}") from exc

    if not pages:
        raise ExtractionError(f"{pdf_path.name} has no pages")

    # Checked here, before anything is detected, so one warning covers a bad map
    # instead of one per page that reads it. A disagreement never stops the run:
    # an unmapped page reports its local number, as a run with no provenance does.
    check_page_map(provenance, page_count, pdf_path.name)

    furniture = detect_furniture(pages, config)
    question_pages = find_question_pages(pages, furniture, config)
    resolved_start = resolve_start_page(question_pages, start_page, page_count)

    calibration: Calibration | None = None
    questions: list[Question] = []
    results: list[PageResult] = []
    end_page: int | None = None

    if resolved_start is None:
        # Nothing anchor-like anywhere: almost always a scanned paper. Emit every
        # page for manual review rather than producing no output at all.
        log.warning(
            "%s: no page contains a recognisable question number - emitting every page "
            "for manual review (a scanned paper needs an OCR pipeline)",
            pdf_path.name,
        )
        resolved_start = 1
        results = _unparsed_results(pages, furniture)
    else:
        end_page = end_paper_at_marker(pages, furniture, config, resolved_start)
        calibration_pages = [p for p in question_pages if p >= resolved_start] or question_pages
        if end_page is not None:
            # Calibration pools leading-x positions across the paper, so a marking
            # scheme left in the sample drags x_cut off the gutter: on one 76-page
            # sample it gave x_cut=39.1 and one question out of eleven.
            calibration_pages = [p for p in calibration_pages if p <= end_page] or calibration_pages
        try:
            calibration = calibrate(pages, furniture, calibration_pages, config)
        except CalibrationError as exc:
            raise ExtractionError(f"{pdf_path.name}: {exc}") from exc

        if resolved_start > 1:
            reason = (
                "as requested" if start_page is not None else "no question numbers found there"
            )
            log.info(
                "starting at page %d, skipping 1-%d (%s)",
                resolved_start,
                resolved_start - 1,
                reason,
            )

        questions, results = build_questions(
            pages, furniture, calibration, resolved_start, config, end_page=end_page
        )
        if not questions:
            log.warning("%s: no questions were detected", pdf_path.name)
        if config.trim_crops:
            trim_bands(pdf_path, pages, furniture, calibration, results, config)

    return LocatedPaper(
        paper=name,
        pdf_path=pdf_path,
        page_count=page_count,
        questions=questions,
        pages=results,
        calibration=calibration,
        start_page=resolved_start,
        end_page=end_page,
    )


def write_renders(
    located: LocatedPaper, out_dir: Path, config: ExtractConfig, debug: bool = False
) -> dict[int, str]:
    """Draw each page whole with the question rectangles in red; ``{page: filename}``.

    ``debug`` also writes the debug renders (calibration and anchors drawn in).
    """
    segment_totals = {q.number: len(q.bands) for q in located.questions}
    args = (
        located.pdf_path, out_dir, located.pages, segment_totals, located.calibration, config
    )
    images = render_pages(*args, debug=False)
    if debug:
        render_pages(*args, debug=True)
    return images


def write_question_manifest(
    located: LocatedPaper,
    out_dir: Path,
    images: dict[int, str],
    config: ExtractConfig,
    warnings: list[str],
    provenance: SourceProvenance | None = None,
) -> Path:
    """Write ``manifest.json`` for a located paper; returns its path."""
    manifest = build_manifest(
        paper=located.paper,
        source_pdf=located.pdf_path,
        page_count=located.page_count,
        start_page=located.start_page,
        end_page=located.end_page,
        questions=located.questions,
        results=located.pages,
        images=images,
        calibration=located.calibration,
        config=config,
        warnings=warnings,
        provenance=provenance,
    )
    return write_manifest(manifest, out_dir)


def extract_paper(
    pdf_path: Path,
    output_root: Path,
    config: ExtractConfig,
    start_page: int | None = None,
    debug: bool = False,
    provenance: SourceProvenance | None = None,
) -> PaperResult:
    """Process one PDF into annotated page renders plus a manifest.

    ``provenance`` is optional: give it when ``pdf_path`` was carved out of a
    larger document and the manifest's page numbers should also be addressable
    there. It changes no detection and, when omitted, no manifest field.

    A sequence of :func:`locate_questions`, :func:`write_renders` and
    :func:`write_question_manifest`.
    """
    with collect_warnings():
        located = locate_questions(pdf_path, config, start_page, provenance)
        out_dir = output_root / located.paper
        images = write_renders(located, out_dir, config, debug)
        manifest_path = write_question_manifest(
            located, out_dir, images, config, current_warnings(), provenance
        )
        log.info(
            "%s: %d question(s) across %d page(s)%s",
            located.paper,
            len(located.questions),
            len(located.pages),
            " - some pages need review" if any(r.needs_review for r in located.pages) else "",
        )
        return PaperResult(
            paper=located.paper,
            out_dir=out_dir,
            questions=located.questions,
            pages=located.pages,
            images=images,
            manifest_path=manifest_path,
            warnings=current_warnings(),
            provenance=provenance,
        )
