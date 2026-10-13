"""Rendering: full pages with the question boundaries drawn on them.

This build does not cut the pages up. Each question page is rendered **whole**
and every question's would-be crop rectangle is drawn on it in red and labelled,
so the detected boundaries can be checked by eye against the printed paper.

All four edges are drawn, not just the horizontal cuts, because two of the four
are calibrated rather than found per question: the left edge is ``x_cut`` and the
right edge is ``content_right``. Seeing them makes it obvious whether the number
gutter is being excluded and whether far-right answer lines are being kept.

Switching to real cropping later is confined to this module: pass ``clip=rect``
to ``get_pixmap`` and write one file per band instead of one per page.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from .boundaries import Band, PageResult
from .calibration import Calibration
from .config import ExtractConfig
from .debug import draw_debug_overlay
from .raster import Draw, draw_on, rasterise_page
from .scanpage import straightened_document
from .webp import write_webp

log = logging.getLogger(__name__)

RED = (0.85, 0.05, 0.05)
DEBUG_SUBDIR = "_debug"
REVIEW_SUBDIR = "review"


def page_filename(page: int) -> str:
    """Output name for an annotated page render."""
    return f"p{page:02d}.png"


def review_filename(page: int) -> str:
    """Output name for a clean review image."""
    return f"p{page:02d}.webp"


def band_label(band: Band, total_segments: int) -> str:
    """Label drawn beside a rectangle, e.g. ``Q7`` or ``Q7 (2/2)``."""
    if total_segments <= 1:
        return f"Q{band.number}"
    return f"Q{band.number} ({band.segment}/{total_segments})"


def render_pages(
    pdf_path: Path,
    out_dir: Path,
    results: list[PageResult],
    segment_totals: dict[int, int],
    config: ExtractConfig,
    debug_draws: dict[int, Draw] | None = None,
    review: bool = False,
    straightened: dict[int, float] | None = None,
) -> dict[int, str]:
    """Render every analysed page once; write its outputs.

    Each page is rasterised once (:func:`.raster.rasterise_page`) and every output
    is that pixmap with marks composited on: ``pNN.png`` with the question
    rectangles drawn on, ``_debug/pNN.png`` with whatever ``debug_draws`` draws for
    the page (the caller's whole overlay, rectangles included, so a debug view
    can be drawn from a saved file), and ``review/pNN.webp`` with nothing drawn,
    from the page as filed. Returns page number to the annotated file name,
    relative to the paper's output folder. The source PDF is opened fresh and
    never saved.

    A page with no bands is still rendered, unannotated: a page the tool could
    not parse is exactly the page a human needs to look at.

    ``straightened`` maps a scanned table page to the rotation it was read after
    (:mod:`.scanpage`); its rectangles are in that frame, so they are drawn on
    the straightened image rather than on the page as filed.
    """
    return render_outputs(
        pdf_path,
        out_dir,
        {
            result.page: _boxes_draw(result, segment_totals)
            for result in results
        },
        config,
        debug_draws=debug_draws,
        review=review,
        straightened=straightened,
    )


def debug_draws(
    results: list[PageResult],
    segment_totals: dict[int, int],
    calibration: Calibration | None,
    config: ExtractConfig,
) -> dict[int, Draw]:
    """Each page's ``--debug`` marks: its rectangles, then every intermediate detection."""
    draws: dict[int, Draw] = {}
    for result in results:
        boxes = _boxes_draw(result, segment_totals)

        def draw(page: pymupdf.Page, result=result, boxes=boxes) -> None:
            boxes(page)
            draw_debug_overlay(page, result, calibration, config)

        draws[result.page] = draw
    return draws


def render_outputs(
    pdf_path: Path,
    out_dir: Path,
    annotated: dict[int, Draw],
    config: ExtractConfig,
    debug_draws: dict[int, Draw] | None = None,
    review: bool = False,
    straightened: dict[int, float] | None = None,
) -> dict[int, str]:
    """Rasterise each page once and write its annotated, debug and review images.

    ``annotated`` and ``debug_draws`` map a page number to the function drawing
    its marks. A page in either is rasterised (once); one in neither is skipped.
    """
    debug_draws = debug_draws or {}
    straightened = straightened or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    if debug_draws:
        (out_dir / DEBUG_SUBDIR).mkdir(exist_ok=True)
    if review:
        (out_dir / REVIEW_SUBDIR).mkdir(exist_ok=True)
    written: dict[int, str] = {}

    with pymupdf.open(pdf_path) as doc:
        for number in sorted(set(annotated) | set(debug_draws)):
            page = doc[number - 1]
            name = page_filename(number)
            if review:
                _write_review(page, out_dir / REVIEW_SUBDIR / review_filename(number), config)

            angle = straightened.get(number)
            sheet = straightened_document(page, angle, config) if angle else None
            if sheet is not None:
                page = sheet[0]
            clean = rasterise_page(page, config.zoom)
            if number in annotated:
                draw_on(clean, page, config.zoom, annotated[number]).save(out_dir / name)
                written[number] = name
            if number in debug_draws:
                draw_on(clean, page, config.zoom, debug_draws[number]).save(
                    out_dir / DEBUG_SUBDIR / name
                )
            if sheet is not None:
                sheet.close()

    log.info("rendered %d page(s) to %s", len(written), out_dir)
    return written


def _write_review(page: pymupdf.Page, path: Path, config: ExtractConfig) -> None:
    """The page as filed, clean, at ``review_zoom``: no rectangles, no straightening.

    The admin review page lays an SVG of the manifest's rectangles over this, in
    the PDF's points scaled by image width over page width, so it has to be the
    page in the PDF's own frame, which a straightened scan is not.
    """
    try:
        write_webp(rasterise_page(page, config.review_zoom), path, config.review_webp_quality)
    except Exception as exc:  # keep the paper going; the review page just lacks this image
        log.warning("%s: review image not written (%s)", path.name, exc)


def _boxes_draw(result: PageResult, segment_totals: dict[int, int]) -> Draw:
    def draw(page: pymupdf.Page) -> None:
        for band in result.bands:
            _draw_band(page, band, segment_totals.get(band.number, 1))

    return draw


def _draw_band(page: pymupdf.Page, band: Band, total_segments: int) -> None:
    """Draw one question's rectangle and its label."""
    page.draw_rect(band.rect, color=RED, width=1.0)

    label = band_label(band, total_segments)
    # Sit the label just above the top edge, dropping it inside the box when the
    # rectangle starts too close to the top of the page for the text to fit.
    baseline_y = band.rect.y0 - 2.5
    if baseline_y < 10.0:
        baseline_y = band.rect.y0 + 9.0
    page.insert_text(
        pymupdf.Point(band.rect.x0 + 2.0, baseline_y),
        label,
        fontsize=8,
        fontname="hebo",
        color=RED,
    )
