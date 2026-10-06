"""Recognising a page that *is* a graph grid.

A question that asks for a graph is answered on printed graph paper, and the
paper gives the whole sheet over to it: the grid runs edge to edge, wider than
the text column and taller than the body of any question. Every geometric rule
in this tool is calibrated on prose — ``x_cut`` and ``content_right`` come from
where the *text* sits — so a grid page is exactly the page those rules describe
worst. Left alone it comes out cropped to a strip of its own grid: on page 11 of
the sample paper the grid reaches x=563.8 and the crop ended at x=372.

The grid also disguises itself as structure it is not. Each of its horizontal
rules is a thin full-width stroke, which is precisely what
:func:`figures._find_dividers` looks for when it hunts the rules a paper prints
between questions, so a grid page reads as a stack of a hundred question
separators.

Both problems dissolve once the page is *named*. The signature is unmistakable
and needs no pixels: **two families of long, evenly spaced, parallel rules
covering most of the body band**. Measured over the sample papers, the two grid
pages carry 91 and 101 rules in their smaller family, and no other page in the
corpus carries more than two — a separation wide enough that the threshold below
is not a tuned number.

Three tests rather than one, because a count alone is not specific. A bordered
table can print a dozen rules; it fails the even-pitch test. A stack of ruled
answer lines can print thirty; it has no vertical family at all, and is left to
the divider logic on purpose.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import pymupdf

from .calibration import cluster_1d
from .config import ExtractConfig
from .furniture import BodyBand
from .geometry import PageGeometry

_POSITION_TOL = 0.5
"""Rules whose leading edges are this close are the same grid line drawn twice."""


@dataclass(frozen=True)
class GridPage:
    """The graph grid found on one page."""

    bbox: pymupdf.Rect
    """Union of every rule that formed the grid."""
    columns: int
    rows: int
    column_pitch: float
    row_pitch: float

    def holds(self, rule: pymupdf.Rect) -> bool:
        """Whether ``rule`` is part of this grid rather than printed beside it.

        Used to tell the grid's own rules from a divider the paper prints above
        or below the grid, which is still a real question separator.
        """
        centre = (rule.y0 + rule.y1) / 2.0
        return self.bbox.y0 <= centre <= self.bbox.y1


def detect_grid(
    page: PageGeometry, band: BodyBand, config: ExtractConfig
) -> GridPage | None:
    """The graph grid on this page, or ``None`` if it carries none.

    Only rules crossing the body band count, so a ruled box in a running footer
    cannot contribute — the same band test :func:`figures.collect_figures` uses.
    """
    verticals: list[pymupdf.Rect] = []
    horizontals: list[pymupdf.Rect] = []
    min_span_x = config.grid_rule_min_span_frac * page.rect.width
    min_span_y = config.grid_rule_min_span_frac * page.rect.height

    for rect in page.drawing_rects:
        if rect.is_infinite or rect.y1 <= band.top or rect.y0 >= band.bottom:
            continue
        if rect.width <= config.grid_rule_max_thickness and rect.height >= min_span_y:
            verticals.append(rect)
        elif rect.height <= config.grid_rule_max_thickness and rect.width >= min_span_x:
            horizontals.append(rect)

    if (
        len(verticals) < config.grid_min_rules
        or len(horizontals) < config.grid_min_rules
    ):
        return None

    column_pitch = _even_pitch([rect.x0 for rect in verticals], config)
    row_pitch = _even_pitch([rect.y0 for rect in horizontals], config)
    if column_pitch is None or row_pitch is None:
        return None

    bbox = _union(verticals + horizontals)
    band_area = max(page.rect.width * (band.bottom - band.top), 1.0)
    if bbox.get_area() < config.grid_min_coverage_frac * band_area:
        return None

    return GridPage(
        bbox=bbox,
        columns=len(cluster_1d([rect.x0 for rect in verticals], _POSITION_TOL)),
        rows=len(cluster_1d([rect.y0 for rect in horizontals], _POSITION_TOL)),
        column_pitch=column_pitch,
        row_pitch=row_pitch,
    )


def _even_pitch(positions: list[float], config: ExtractConfig) -> float | None:
    """The spacing of these rules, or ``None`` if they are not evenly spaced.

    A grid is defined by its regularity, and this is the test a table's borders
    fail: they are as thin and as long as grid rules but sit wherever the table's
    columns happen to fall. Most of the gaps must match the median, not all of
    them — a graph grid prints a heavier rule every fifth line, and where two are
    drawn on top of each other the pair reads as one short gap.
    """
    centres = [
        sum(cluster) / len(cluster)
        for cluster in cluster_1d(positions, _POSITION_TOL)
    ]
    gaps = [b - a for a, b in zip(centres, centres[1:])]
    if len(gaps) < config.grid_min_rules - 1:
        return None

    pitch = statistics.median(gaps)
    if pitch <= 0:
        return None
    regular = sum(1 for gap in gaps if abs(gap - pitch) <= config.grid_pitch_tol * pitch)
    if regular < config.grid_regular_frac * len(gaps):
        return None
    return pitch


def _union(rects: list[pymupdf.Rect]) -> pymupdf.Rect:
    """Box enclosing every rule.

    Built from explicit ``min``/``max`` rather than ``Rect.__or__``, which drops
    a rect PyMuPDF calls empty — and a grid rule drawn as a stroke has no width
    or no height at all, so every one of them is empty by that definition.
    """
    return pymupdf.Rect(
        min(rect.x0 for rect in rects),
        min(rect.y0 for rect in rects),
        max(rect.x1 for rect in rects),
        max(rect.y1 for rect in rects),
    )
