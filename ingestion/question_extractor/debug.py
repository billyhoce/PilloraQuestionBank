"""Diagnostic overlay for ``--debug``.

The red rectangles say *where* the tool decided to cut. When one of them is
wrong, this overlay says *why* — it exposes each intermediate detection, so a
misplaced edge can be traced to the stage responsible:

======================  ==========================================
Blue dashed verticals   ``x_cut`` and ``content_right``, the crop's limits
Yellow shaded bands     running header / footer, excluded from questions
Green markers           detected anchors, at their corrected tops
Green boxes             figure and diagram boxes eligible for unioning
Magenta lines           divider rules used to confirm boundaries
Cyan box                a graph grid, and the page it takes over
Orange dashed box       ink a pixel scan found where geometry was blind
Grey dashed boxes       each question's untrimmed share of the page
======================  ==========================================

The orange box appears only on a scanned page, where the text layer is the whole
of the geometry and the drawn content is invisible to it. It is what the trim
would have missed: if a crop on such a page is wrong, whether the box encloses
the content says at once which side of :mod:`.trim` to look at.

The grey boxes are why this overlay is worth keeping after trimming: the red
rectangle now hugs the ink, so it no longer shows where one question was judged
to end and the next to begin — and it is *that* judgement the paper's printed
divider rules confirm.
"""

from __future__ import annotations

import pymupdf

from .boundaries import PageResult
from .calibration import Calibration
from .config import ExtractConfig
from .figures import real_figures

BLUE = (0.1, 0.35, 0.9)
GREEN = (0.0, 0.55, 0.2)
GREY = (0.55, 0.55, 0.55)
MAGENTA = (0.8, 0.0, 0.8)
YELLOW = (0.75, 0.65, 0.0)
CYAN = (0.0, 0.6, 0.7)
ORANGE = (0.9, 0.45, 0.0)


def draw_debug_overlay(
    page: pymupdf.Page,
    result: PageResult,
    calibration: Calibration | None,
    config: ExtractConfig,
) -> None:
    """Draw every intermediate detection for one page onto that page.

    ``calibration`` is ``None`` for a paper no question number was found in; the
    stages that did run are still drawn, which is what shows why the rest did not.
    """
    rect = page.rect

    if calibration is not None:
        _draw_calibration_lines(page, rect, calibration)
        _draw_anchors(page, result, calibration)
    _draw_partitions(page, result)
    _draw_pixel_ink(page, result)
    if result.body_band is not None:
        shade_furniture(page, rect, result.body_band)
    if result.figures is not None:
        _draw_figures(page, result, config)
    if result.grid is not None:
        _draw_grid(page, result.grid)
    _draw_legend(page, rect, calibration, result)


def _draw_grid(page: pymupdf.Page, grid) -> None:
    """Outline a recognised graph grid and say what was measured.

    The grid's own rules are not drawn - they are the page. What is worth seeing
    is the box the detector agreed on and the pitch that convinced it, since a
    near miss on either is what a false negative would look like.
    """
    page.draw_rect(grid.bbox, color=CYAN, width=1.2)
    page.insert_text(
        pymupdf.Point(grid.bbox.x0 + 2.0, grid.bbox.y0 - 3.0),
        f"grid {grid.columns}x{grid.rows} @ "
        f"{grid.column_pitch:.2f} x {grid.row_pitch:.2f}pt",
        fontsize=7,
        fontname="hebo",
        color=CYAN,
    )


def _draw_calibration_lines(
    page: pymupdf.Page, rect: pymupdf.Rect, calibration: Calibration
) -> None:
    for x in (calibration.x_cut, calibration.content_right):
        page.draw_line(
            pymupdf.Point(x, rect.y0),
            pymupdf.Point(x, rect.y1),
            color=BLUE,
            width=0.4,
            dashes="[3 3] 0",
        )


def _draw_partitions(page: pymupdf.Page, result: PageResult) -> None:
    """Outline each question's untrimmed share of the page.

    Drawn even when it matches the red rectangle exactly — a band that did not
    trim is worth seeing as such.
    """
    for band in result.bands:
        if band.partition is None:
            continue
        page.draw_rect(band.partition, color=GREY, width=0.5, dashes="[4 3] 0")


def _draw_pixel_ink(page: pymupdf.Page, result: PageResult) -> None:
    """Outline the ink box the pixel fallback supplied, where it ran."""
    for band in result.bands:
        if band.pixel_ink_box is None:
            continue
        page.draw_rect(
            band.pixel_ink_box, color=ORANGE, width=0.6, dashes="[2 2] 0"
        )


def shade_furniture(page: pymupdf.Page, rect: pymupdf.Rect, band) -> None:
    """Shade the header and footer strips that questions may not occupy."""
    for strip in (
        pymupdf.Rect(rect.x0, rect.y0, rect.x1, band.top),
        pymupdf.Rect(rect.x0, band.bottom, rect.x1, rect.y1),
    ):
        if strip.height <= 0:
            continue
        page.draw_rect(strip, color=YELLOW, fill=YELLOW, fill_opacity=0.12, width=0.3)


def _draw_figures(page: pymupdf.Page, result: PageResult, config: ExtractConfig) -> None:
    # Only the boxes a reader would call a figure; glyph-sized strokes add noise.
    for box in real_figures(result.figures.figures, config):
        page.draw_rect(box, color=GREEN, width=0.5, dashes="[2 2] 0")
    for rule in result.figures.dividers:
        page.draw_line(
            pymupdf.Point(rule.x0, (rule.y0 + rule.y1) / 2.0),
            pymupdf.Point(rule.x1, (rule.y0 + rule.y1) / 2.0),
            color=MAGENTA,
            width=1.2,
        )


def _draw_anchors(page: pymupdf.Page, result: PageResult, calibration: Calibration) -> None:
    """Mark each anchor's number and the corrected top derived from its row."""
    for anchor in result.anchors:
        page.draw_rect(anchor.line.rect, color=GREEN, width=0.6)
        page.draw_line(
            pymupdf.Point(anchor.line.x0 - 6.0, anchor.top),
            pymupdf.Point(calibration.x_cut, anchor.top),
            color=GREEN,
            width=0.8,
        )


def _draw_legend(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    calibration: Calibration | None,
    result: PageResult,
) -> None:
    """Print the calibrated values so a render is self-describing."""
    if result.skip_reason is not None:
        text = f"p{result.page}  skipped - {result.skip_reason}"
    elif calibration is None:
        text = f"p{result.page}  not calibrated - {result.review_reason}"
    else:
        text = (
            f"p{result.page}  x_cut={calibration.x_cut:.1f}  "
            f"content_right={calibration.content_right:.1f}  "
            f"gutter={calibration.gutter_x:.1f}  content={calibration.content_x:.1f}  "
            f"anchors={[a.number for a in result.anchors]}"
        )
    page.insert_text(
        pymupdf.Point(rect.x0 + 6.0, rect.y1 - 5.0),
        text,
        fontsize=6,
        fontname="helv",
        color=BLUE,
    )
