"""Figure, diagram and divider geometry.

Two jobs, both driven by the same raw boxes:

* **Figures** — embedded images and vector drawings that belong to a question.
  Their boxes are unioned into the crop rectangle so a Venn diagram wider or
  taller than the surrounding text is not clipped.
* **Dividers** — the thin full-width rules some papers print between questions.
  They are *excluded* from the figure union (in the sample paper they run from
  x=58.7 to x=545.5, wider than the text margin, so unioning one would drag the
  crop's left edge back over the question number) and used only to confirm a
  boundary that whitespace analysis already found.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

from .calibration import Calibration
from .config import ExtractConfig
from .furniture import BodyBand
from .geometry import PageGeometry


@dataclass
class PageFigures:
    """The usable figure boxes and divider rules of one page."""

    figures: list[pymupdf.Rect] = field(default_factory=list)
    dividers: list[pymupdf.Rect] = field(default_factory=list)

    def divider_between(self, top: float, bottom: float) -> pymupdf.Rect | None:
        """The first divider whose centre lies strictly inside ``(top, bottom)``."""
        for rule in self.dividers:
            centre = (rule.y0 + rule.y1) / 2.0
            if top < centre < bottom:
                return rule
        return None


def real_figures(
    boxes: list[pymupdf.Rect], config: ExtractConfig
) -> list[pymupdf.Rect]:
    """The boxes big enough to be figures rather than single glyph strokes.

    A page of algebra produces dozens of tiny vector boxes — fraction bars, the
    strokes of a surd — which are content in the sense that they belong to a
    question, but are not evidence *that* there is a question. Callers deciding
    "does this page carry anything" or drawing diagnostics want only the boxes a
    reader would call a figure.
    """
    return [
        box
        for box in boxes
        if box.width > config.min_figure_span or box.height > config.min_figure_span
    ]


def overlapping_figures(
    figures: list[pymupdf.Rect], top: float, bottom: float, config: ExtractConfig
) -> list[pymupdf.Rect]:
    """The figures belonging to the band between ``top`` and ``bottom``.

    The test is purely vertical — a figure belongs to the question whose band it
    sits in — and it demands a real share of the figure's height, so a diagram
    that merely grazes a boundary is not claimed by both questions either side.
    """
    kept: list[pymupdf.Rect] = []
    for rect in figures:
        overlap = min(bottom, rect.y1) - max(top, rect.y0)
        if overlap <= 0:
            continue
        if rect.height > 0 and overlap < config.figure_min_overlap * rect.height:
            continue
        kept.append(rect)
    return kept


_RULE_ROW_TOL = 1.5
"""Thin rects whose centres are this close vertically belong to the same rule."""


def _find_dividers(
    rects: list[pymupdf.Rect], page: PageGeometry, config: ExtractConfig
) -> tuple[list[pymupdf.Rect], set[int]]:
    """Group thin rects into rules and return those wide enough to be dividers.

    A divider is rarely a single rect. In the sample paper each one is drawn as
    five abutting fills — two short end caps and a long middle — and testing each
    fragment on its own recognises only the middle. The fragments are therefore
    grouped by height and judged on their combined span, and every fragment of a
    qualifying rule is excluded from the figure set (an end cap left behind would
    otherwise register as content sitting exactly in the whitespace where the
    boundary belongs, and split the gap in two).

    Returns the composite divider rectangles and the ``id()``s of every fragment
    that formed one.
    """
    thin = [r for r in rects if r.height <= config.divider_max_height]
    thin.sort(key=lambda r: (r.y0 + r.y1) / 2.0)

    dividers: list[pymupdf.Rect] = []
    fragment_ids: set[int] = set()
    group: list[pymupdf.Rect] = []

    def flush() -> None:
        if not group:
            return
        span = max(r.x1 for r in group) - min(r.x0 for r in group)
        if span >= config.divider_min_width_frac * page.width:
            composite = pymupdf.Rect(group[0])
            for rect in group[1:]:
                composite |= rect
            dividers.append(composite)
            fragment_ids.update(id(rect) for rect in group)

    for rect in thin:
        centre = (rect.y0 + rect.y1) / 2.0
        if group and centre - (group[-1].y0 + group[-1].y1) / 2.0 > _RULE_ROW_TOL:
            flush()
            group = []
        group.append(rect)
    flush()

    return dividers, fragment_ids


def collect_figures(page: PageGeometry, band: BodyBand, config: ExtractConfig) -> PageFigures:
    """Split a page's boxes into question figures and divider rules."""
    result = PageFigures()
    page_area = max(page.width * page.height, 1.0)
    # Zero-height rects are kept: a divider drawn as a stroke rather than a fill
    # has no height at all, and PyMuPDF calls such a rect "empty".
    candidates = [
        rect
        for rect in list(page.image_rects) + list(page.drawing_rects)
        if not rect.is_infinite and (rect.width > 0 or rect.height > 0)
    ]

    result.dividers, divider_fragments = _find_dividers(candidates, page, config)

    for rect in candidates:
        if id(rect) in divider_fragments:
            continue
        if rect.y1 <= band.top or rect.y0 >= band.bottom:
            continue  # header/footer decoration, e.g. a page logo
        if rect.get_area() >= config.figure_max_area_frac * page_area:
            continue  # full-page background fill
        result.figures.append(rect)

    result.dividers.sort(key=lambda r: r.y0)
    result.figures.sort(key=lambda r: r.y0)
    return result


def union_figures(
    crop: pymupdf.Rect,
    figures: list[pymupdf.Rect],
    page: PageGeometry,
    calibration: Calibration,
    config: ExtractConfig,
    top_limit: float,
    bottom_limit: float,
) -> tuple[pymupdf.Rect, bool]:
    """Widen ``crop`` to enclose any figure overlapping it vertically.

    Returns the new rectangle and whether any figure actually changed it.

    Figures may push the right edge past ``content_right`` (a diagram can be
    wider than the text) but never past the page's right margin, and never left
    of ``x_cut`` — the question number must stay outside the crop whatever the
    surrounding vector art does. Vertically they may reach ``top_limit`` and
    ``bottom_limit``, which are the neighbouring question boundaries, so a
    diagram taller than the text is kept while never bleeding into the question
    above or below.
    """
    result = pymupdf.Rect(crop)
    left_limit = calibration.x_cut
    right_limit = page.rect.x1 - config.min_right_margin
    changed = False

    for rect in overlapping_figures(figures, result.y0, result.y1, config):
        widened = pymupdf.Rect(
            max(left_limit, min(result.x0, rect.x0)),
            max(top_limit, min(result.y0, rect.y0)),
            min(right_limit, max(result.x1, rect.x1)),
            min(bottom_limit, max(result.y1, rect.y1)),
        )
        if widened != result:
            result = widened
            changed = True

    return result, changed
