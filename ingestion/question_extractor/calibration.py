"""Calibration of the horizontal crop edges.

Two x-values describe a paper's layout:

``x_cut``
    The boundary between the number gutter and the content column. Question
    numbers sit left of it and are excluded from the crop; part labels such as
    ``(a)`` and ``(i)`` sit at or right of it and are kept. This is the crop's
    **left** edge — deliberately not "the first token after the number", which
    is what makes a shared ``7  (a)`` line come out right for free.

``content_right``
    The page-wide right content margin. Taken across the whole paper rather than
    from the nearest text cluster, so far-right answer lines and mark brackets
    like ``[2]`` fall inside the crop.

``x_cut`` is found by clustering the x-position of every line's leading token.
A well-formed question page yields one cluster in the gutter (the numbers) and
one in the content column; ``x_cut`` is the midpoint of the gap between them.

A page that sets its question numbers further right than the rest of the paper
gets its own ``x_cut`` (:func:`with_page_cuts`); :meth:`Calibration.for_page`
is what every per-page reader goes through.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace

from .config import ExtractConfig
from .furniture import Furniture
from .geometry import PageGeometry, TextLine
from .tokens import is_anchor_token

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Calibration:
    """Horizontal layout of a paper."""

    x_cut: float
    content_right: float
    gutter_x: float
    """Left edge of the number gutter (for reporting and debug overlays)."""
    content_x: float
    """Left edge of the content column."""
    confident: bool
    """False when no distinct gutter cluster was found and a fallback was used."""
    page_cuts: dict[int, float] = field(default_factory=dict)
    """``x_cut`` of each page that indents its question numbers past the paper's."""

    def for_page(self, page: int) -> Calibration:
        """This calibration as seen from one page: ``x_cut`` is that page's own."""
        cut = self.page_cuts.get(page)
        return self if cut is None else replace(self, x_cut=cut, page_cuts={})

    def entry(self) -> dict:
        """JSON-ready: the fields by name, ``page_cuts`` keyed by page number as text."""
        return {
            "x_cut": self.x_cut,
            "content_right": self.content_right,
            "gutter_x": self.gutter_x,
            "content_x": self.content_x,
            "confident": self.confident,
            "page_cuts": {str(page): cut for page, cut in self.page_cuts.items()},
        }

    @classmethod
    def from_entry(cls, entry: dict) -> Calibration:
        page_cuts = {int(page): cut for page, cut in entry.get("page_cuts", {}).items()}
        return cls(**{**entry, "page_cuts": page_cuts})


def gutter_candidates(
    geom: PageGeometry, body_lines: list[TextLine], config: ExtractConfig
) -> list[TextLine]:
    """Lines that could be question numbers, before ``x_cut`` is known.

    Used to pick the pages worth calibrating on, so calibration never has to
    look at a cover page or formula sheet whose left margin means something
    different. The window is generous — ``x_cut`` itself is derived later.
    """
    limit = geom.rect.x0 + config.gutter_search_frac * geom.width
    return [
        line
        for line in body_lines
        if line.leading_x <= limit and is_anchor_token(line.leading_token)
    ]


def find_question_pages(
    pages: list[PageGeometry], furniture: Furniture, config: ExtractConfig
) -> list[int]:
    """Page numbers that carry at least one plausible question number.

    A formula sheet has all of its leading tokens in the content column and so
    contributes nothing here, which is what lets the start page be inferred
    rather than configured.
    """
    found: list[int] = []
    for geom in pages:
        if not geom.has_text:
            continue
        if gutter_candidates(geom, furniture.body_lines(geom), config):
            found.append(geom.number)
    return found


def cluster_1d(values: list[float], tol: float) -> list[list[float]]:
    """Group sorted 1-D values, splitting wherever the gap exceeds ``tol``."""
    clusters: list[list[float]] = []
    for value in sorted(values):
        if clusters and value - clusters[-1][-1] <= tol:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return clusters


def calibrate(
    pages: list[PageGeometry],
    furniture: Furniture,
    page_numbers: list[int],
    config: ExtractConfig,
) -> Calibration:
    """Derive ``x_cut`` and ``content_right`` from the paper's question pages.

    Calibration is done once per paper rather than per page: individual pages
    can be short on lines, and papers are internally consistent enough that the
    pooled histogram is the more reliable signal.
    """
    selected = [geom for geom in pages if geom.number in set(page_numbers)]
    if not selected:
        raise CalibrationError("no question pages to calibrate on")

    leading_xs: list[float] = []
    number_xs: list[float] = []
    right_edges: list[float] = []
    for geom in selected:
        body = furniture.body_lines(geom)
        leading_xs.extend(line.leading_x for line in body)
        right_edges.extend(line.x1 for line in body)
        number_xs.extend(line.leading_x for line in gutter_candidates(geom, body, config))

    if not leading_xs or not number_xs:
        raise CalibrationError("question pages yielded no leading-token positions")

    page_rect = selected[0].rect
    gutter_x, content_x, x_cut, confident = _split_columns(leading_xs, number_xs, config)
    content_right = _content_right(right_edges, page_rect.x1, config)

    if content_right <= x_cut:
        raise CalibrationError(
            f"degenerate horizontal calibration (x_cut={x_cut:.1f} >= "
            f"content_right={content_right:.1f})"
        )

    log.debug(
        "calibrated on %d page(s): gutter_x=%.1f content_x=%.1f x_cut=%.1f content_right=%.1f",
        len(selected),
        gutter_x,
        content_x,
        x_cut,
        content_right,
    )
    return Calibration(
        x_cut=x_cut,
        content_right=content_right,
        gutter_x=gutter_x,
        content_x=content_x,
        confident=confident,
    )


def _split_columns(
    leading_xs: list[float], number_xs: list[float], config: ExtractConfig
) -> tuple[float, float, float, bool]:
    """Locate the gutter and content clusters and the cut between them."""
    clusters = cluster_1d(leading_xs, config.cluster_tol)
    leftmost_number = min(number_xs)

    gutter_index = next(
        (i for i, c in enumerate(clusters) if c[0] <= leftmost_number <= c[-1]),
        0,
    )
    gutter = clusters[gutter_index]
    gutter_x, gutter_right = gutter[0], gutter[-1]

    content = next(
        (
            c
            for c in clusters[gutter_index + 1 :]
            if len(c) >= config.min_cluster_support and c[0] - gutter_right >= config.min_gutter_gap
        ),
        None,
    )

    if content is not None:
        # A question number left of the content column is in the gutter even when it
        # sits clear of the gutter's own cluster: on a scan the sheet shifts from page
        # to page, and Yuying's Q1 is set 8pt right of its other numbers, which put the
        # cut through it and lost the question.
        gutter_right = max([gutter_right, *(x for x in number_xs if x < content[0])])
        return gutter_x, content[0], (gutter_right + content[0]) / 2.0, True

    # No cleanly separated content column: fall back to the nearest thing to the
    # right of the gutter and cut just left of it, warning loudly.
    fallback = next((c[0] for c in clusters[gutter_index + 1 :]), gutter_right + config.min_gutter_gap)
    x_cut = max(gutter_right + 1.0, fallback - config.x_cut_fallback_pad)
    log.warning(
        "no distinct content column found right of the gutter (gutter ends at %.1f); "
        "falling back to x_cut=%.1f - check the debug overlay",
        gutter_right,
        x_cut,
    )
    return gutter_x, fallback, x_cut, False


def with_page_cuts(
    calibration: Calibration,
    pages: list[PageGeometry],
    furniture: Furniture,
    config: ExtractConfig,
) -> Calibration:
    """``calibration`` with an ``x_cut`` of their own for pages that need one.

    The answer booklet of BPGHS 2020 EM P1 indents Q1 and Q2 on its first page to
    x=54-56, where every other page sets its numbers at x=33-41. The paper's cut,
    52.0, read them as body text and the page as a continuation with no question
    open, so neither question got an answer. The rule for a shifted number in
    :func:`_split_columns` could not save them: on that scan the content column's
    cluster chains rightwards from 53.5, so they are not left of it.
    """
    cuts: dict[int, float] = {}
    for geom in pages:
        if not geom.has_text:
            continue
        cut = _indented_cut(furniture.body_lines(geom), calibration.x_cut, config)
        if cut is not None:
            log.info(
                "page %d: question numbers set right of x_cut=%.1f; using x_cut=%.1f on this page",
                geom.number,
                calibration.x_cut,
                cut,
            )
            cuts[geom.number] = cut
    return replace(calibration, page_cuts=cuts) if cuts else calibration


def _indented_cut(body_lines: list[TextLine], x_cut: float, config: ExtractConfig) -> float | None:
    """A page's own ``x_cut``, or ``None`` when the paper's serves it.

    Asked only of a page with no question number left of the paper's cut. The
    page's numbers must stand ``min_gutter_gap`` clear of every other line right
    of that cut, so a number inside the text — a lone ``2`` among a display's
    fragments, set left of the next fragment but right of the prose — never
    qualifies.
    """
    if any(line.leading_x <= x_cut and is_anchor_token(line.leading_token) for line in body_lines):
        return None
    right = [line for line in body_lines if line.leading_x > x_cut]
    text = [line.leading_x for line in right if not is_anchor_token(line.leading_token)]
    if not text:
        return None
    content_x = min(text)
    gutter = [
        line.leading_x
        for line in right
        if is_anchor_token(line.leading_token)
        and line.leading_x <= content_x - config.min_gutter_gap
    ]
    return (max(gutter) + content_x) / 2.0 if gutter else None


def _content_right(right_edges: list[float], page_right: float, config: ExtractConfig) -> float:
    """Right crop edge: the widest body text on any question page, plus a pad."""
    widest = max(right_edges)
    return min(widest + config.content_right_pad, page_right - config.min_right_margin)


class CalibrationError(RuntimeError):
    """Raised when a paper's horizontal layout cannot be determined."""
