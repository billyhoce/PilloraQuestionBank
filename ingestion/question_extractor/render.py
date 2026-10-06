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
from .scanpage import straightened_document

log = logging.getLogger(__name__)

RED = (0.85, 0.05, 0.05)
DEBUG_SUBDIR = "_debug"


def page_filename(page: int) -> str:
    """Output name for an annotated page render."""
    return f"p{page:02d}.png"


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
    calibration: Calibration | None,
    config: ExtractConfig,
    debug: bool = False,
    straightened: dict[int, float] | None = None,
) -> dict[int, str]:
    """Render every analysed page with its question rectangles drawn on.

    Returns a mapping of page number to the file name written, relative to the
    paper's output folder. The source PDF is opened fresh and never saved, so
    the annotations exist only in the rendered PNGs.

    A page with no bands is still rendered, unannotated: a page the tool could
    not parse is exactly the page a human needs to look at.

    ``straightened`` maps a scanned table page to the rotation it was read after
    (:mod:`.scanpage`); its rectangles are in that frame, so they are drawn on
    the straightened image rather than on the page as filed.
    """
    target = out_dir / DEBUG_SUBDIR if debug else out_dir
    target.mkdir(parents=True, exist_ok=True)
    matrix = pymupdf.Matrix(config.zoom, config.zoom)
    written: dict[int, str] = {}
    straightened = straightened or {}

    with pymupdf.open(pdf_path) as doc:
        for result in results:
            page = doc[result.page - 1]
            angle = straightened.get(result.page)
            sheet = straightened_document(page, angle, config) if angle else None
            if sheet is not None:
                page = sheet[0]

            for band in result.bands:
                _draw_band(page, band, segment_totals.get(band.number, 1))

            if debug:
                draw_debug_overlay(page, result, calibration, config)

            pixmap = page.get_pixmap(matrix=matrix)
            name = page_filename(result.page)
            pixmap.save(target / name)
            written[result.page] = f"{DEBUG_SUBDIR}/{name}" if debug else name
            if sheet is not None:
                sheet.close()

    log.info("rendered %d annotated page(s) to %s", len(written), target)
    return written


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
