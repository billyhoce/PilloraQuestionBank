"""Question boundaries and cross-page grouping.

A question runs from its own anchor to the start of the next one, but the next
anchor's y-position is *not* the right place to cut. In the sample paper Q2's
number sits at y=268.2 while the display fraction that belongs to Q2 starts at
y=257.5 — eleven points higher, because the number is centred against the
fraction. Cutting at the anchor would slice that numerator into Q1.

So every boundary is **snapped into the whitespace** that separates the two
questions — the gap immediately above the anchor. Where a paper prints divider
rules, a divider inside that gap wins, which is the confirmation path the rules
describe. On the sample page the whitespace midpoint lands at y≈241.4 and the
printed divider at y≈242.7 — the two agree to about a point, which is what says
the whitespace reasoning is sound on papers that print no dividers at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pymupdf

from .anchors import Anchor, find_page_anchors, filter_sequence
from .calibration import Calibration
from .config import ExtractConfig
from .figures import PageFigures, collect_figures, union_figures
from .furniture import BodyBand, Furniture
from .geometry import PageGeometry
from .gridpage import GridPage, detect_grid
from .pagekind import blank_page_reason
from .tokens import is_part_label

log = logging.getLogger(__name__)

Interval = tuple[float, float]


@dataclass
class Band:
    """One question's crop rectangle on one page."""

    page: int
    number: int
    rect: pymupdf.Rect
    partition: pymupdf.Rect | None = None
    """The untrimmed rectangle: this question's whole share of the page.

    ``rect`` is trimmed onto the question's ink afterwards, which is a better
    crop but no longer shows where one question was judged to end and the next to
    begin. That judgement is what the paper's printed divider rules confirm, so
    it is kept here and reported rather than thrown away.
    """
    segment: int = 1
    """1-based index of this page within the question."""
    is_continuation: bool = False
    """True when this band continues a question started on an earlier page."""
    figure_extended: bool = False
    """True when a figure or diagram box widened the rectangle."""
    grid_page: bool = False
    """True when the page is a graph grid, and the rectangle was widened onto it."""
    pixel_ink_box: pymupdf.Rect | None = None
    """The ink box rendered pixels supplied, on a page whose geometry was blind.

    Set by :mod:`.trim` only on a scan, where the text layer is the sole geometry
    and it does not see the drawn diagrams. Kept rather than folded away so
    ``--debug`` can draw it: when a trimmed edge on a scan looks wrong, this box
    says whether the pixels or the geometry put it there.
    """

    @property
    def pixel_ink(self) -> bool:
        """True when the pixel fallback contributed to this band's ink box."""
        return self.pixel_ink_box is not None


@dataclass
class Question:
    """A question and the per-page bands it occupies."""

    number: int
    bands: list[Band] = field(default_factory=list)

    @property
    def pages(self) -> list[int]:
        return [band.page for band in self.bands]


@dataclass
class PageResult:
    """Per-page outcome, including pages that could not be parsed.

    Also carries the intermediate detections (anchors, figures, body band) so
    ``--debug`` can draw them without re-running the analysis.
    """

    page: int
    bands: list[Band] = field(default_factory=list)
    has_text: bool = True
    needs_review: bool = False
    review_reason: str | None = None
    skip_reason: str | None = None
    """Why the page carries no question at all, e.g. a printed ``BLANK PAGE``."""
    anchors: list[Anchor] = field(default_factory=list)
    figures: PageFigures | None = None
    body_band: BodyBand | None = None
    grid: GridPage | None = None
    """The graph grid covering this page, when it is graph paper."""
    continuation_note: str | None = None
    """Why the page was read as continuing the previous question, if it was."""


def _merged_intervals(
    page: PageGeometry, furniture: Furniture, figures: PageFigures
) -> list[Interval]:
    """Vertical spans occupied by content, overlapping spans merged.

    Text lines and figure boxes both count: a diagram is as much a reason not to
    cut at a given height as a line of text is.
    """
    spans = [(line.y0, line.y1) for line in furniture.body_lines(page)]
    spans += [(rect.y0, rect.y1) for rect in figures.figures]
    spans.sort()

    merged: list[Interval] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _snap_boundary(
    raw: float,
    intervals: list[Interval],
    figures: PageFigures,
    low_limit: float,
    config: ExtractConfig,
) -> float:
    """Place a question boundary in the whitespace above ``raw``.

    ``raw`` is the next anchor's corrected top and ``low_limit`` keeps the
    boundary below the previous question's own start. The separator is the gap
    immediately above the anchor — the whitespace the anchor sits at the foot of —
    and it is resolved in this order:

    1. A **divider rule** inside the gap wins outright: the paper itself is
       saying where the question ends, whatever the whitespace looks like.
    2. Otherwise the gap's **midpoint**, provided the gap is modest enough for
       the midpoint to be meaningful (within ``snap_lookback`` of the anchor).
    3. Otherwise **just above the anchor**. A large undivided blank is a
       question's answer space, and answer space belongs to the question it was
       left for, not to the one below it.
    """
    above = [end for _, end in intervals if end <= raw + 1.0]
    spans_raw = any(start < raw < end for start, end in intervals)

    if not above or spans_raw:
        log.debug("no clean whitespace above y=%.1f; cutting at the anchor", raw)
        return max(low_limit, raw - config.band_top_pad)

    gap_start, gap_end = max(above), raw

    divider = figures.divider_between(gap_start, gap_end)
    if divider is not None:
        boundary = (divider.y0 + divider.y1) / 2.0
    elif (
        gap_end - gap_start >= config.min_snap_gap
        and (gap_start + gap_end) / 2.0 >= raw - config.snap_lookback
    ):
        boundary = (gap_start + gap_end) / 2.0
    else:
        boundary = raw - config.band_top_pad

    return min(max(boundary, low_limit), raw + config.snap_lookahead)


def _page_bottom(
    intervals: list[Interval], figures: PageFigures, band: BodyBand
) -> float:
    """Where the last question on a page ends.

    The body band's bottom is the backstop. If the paper prints a divider below
    the last piece of content, that is a tighter and more faithful end — it is
    exactly where the paper itself says the question stops.
    """
    if not intervals:
        return band.bottom
    last_content_end = intervals[-1][1]
    divider = figures.divider_between(last_content_end, band.bottom)
    if divider is not None:
        return (divider.y0 + divider.y1) / 2.0
    return band.bottom


def _make_band(
    page: PageGeometry,
    number: int,
    top: float,
    bottom: float,
    figures: PageFigures,
    calibration: Calibration,
    config: ExtractConfig,
    is_continuation: bool,
    band_limits: BodyBand,
    grid: GridPage | None = None,
) -> Band | None:
    """Build one band's crop rectangle, including any figure union.

    On a graph-grid page the calibrated horizontal edges are abandoned: ``x_cut``
    and ``content_right`` describe where the paper's *prose* sits, and the grid
    runs past both of them into the margins. The rectangle is widened onto the
    grid's own bounding box instead — to the grid, not to the sheet, so the crop
    does not carry the page's blank margins with it.

    Only the horizontal edges move. The vertical share is the boundary stage's
    decision and stays exactly as it was, which is what keeps a grid page carrying
    two questions splitting between them; each half simply spans the grid.
    """
    crop = pymupdf.Rect(calibration.x_cut, top, calibration.content_right, bottom)
    if crop.is_empty or crop.height <= 1.0:
        log.warning(
            "page %d: question %d produced a degenerate crop rectangle (height %.1f); skipping",
            page.number,
            number,
            crop.height,
        )
        return None
    if grid is not None:
        crop = _widen_to_grid(crop, grid, page, band_limits, config)
        extended = False
    else:
        crop, extended = union_figures(
            crop,
            figures.figures,
            page,
            calibration,
            config,
            top_limit=top,
            bottom_limit=bottom,
        )
    return Band(
        page=page.number,
        number=number,
        rect=crop,
        partition=pymupdf.Rect(crop),
        is_continuation=is_continuation,
        figure_extended=extended,
        grid_page=grid is not None,
    )


def _widen_to_grid(
    crop: pymupdf.Rect,
    grid: GridPage,
    page: PageGeometry,
    band: BodyBand,
    config: ExtractConfig,
) -> pymupdf.Rect:
    """``crop`` widened onto the grid, and no further.

    Sideways it reaches the grid plus the pad the trim pass leaves around ink
    everywhere else, so the grid ends up with the clearance a diagram gets.
    Widening to the *page* instead would be simpler and is wrong: on the sample
    paper the grid stops 35.6pt short of the left edge and 31.6pt short of the
    right, and a crop taken to the sheet carries both margins with it. Never
    narrower than the calibrated column either, since a grid narrower than the
    text would otherwise cut into a question's own words.

    Vertically the body band is the usual limit, but a grid is quite happy to run
    past it — the band is derived from where the running header and footer sit,
    and on the sample paper the last rule lies 5.4pt below it, a whole plotting
    row. So an edge the band owns outright follows the grid instead. An edge
    shared with another question never moves: it is that question's edge too.

    The bottom follows the grid *without* the pad. It is the one edge that can
    reach into a running footer, and stopping on the last rule is enough.
    """
    pad = config.crop_pad
    box = grid.bbox
    top = min(crop.y0, box.y0 - pad) if crop.y0 <= band.top else crop.y0
    bottom = max(crop.y1, box.y1) if crop.y1 >= band.bottom else crop.y1
    return pymupdf.Rect(
        max(page.rect.x0, min(crop.x0, box.x0 - pad)),
        max(page.rect.y0, top),
        min(page.rect.x1, max(crop.x1, box.x1 + pad)),
        min(page.rect.y1, bottom),
    )


def _continuation_note(page: PageGeometry, furniture: Furniture) -> str:
    """Describe why a page reads as a continuation, for the manifest.

    Both wordings describe the same geometric finding — no question number above
    the page's first content — but naming the part label makes an unexpected
    grouping much quicker to explain.
    """
    lines = furniture.body_lines(page)
    if lines:
        first = min(lines, key=lambda ln: (ln.y0, ln.x0))
        if is_part_label(first.leading_token):
            return f"page opens with part label {first.leading_token!r}"
    return "page opens with body content and no question number above it"


def _first_content_top(
    page: PageGeometry, furniture: Furniture, figures: PageFigures
) -> float | None:
    """Top of the highest piece of body content on a page."""
    tops = [line.y0 for line in furniture.body_lines(page)]
    tops += [rect.y0 for rect in figures.figures]
    return min(tops) if tops else None


def _has_content_above(
    page: PageGeometry, furniture: Furniture, figures: PageFigures, limit: float
) -> bool:
    """Whether any body content lies wholly above ``limit``.

    The test is *wholly* above, and ``limit`` is the boundary rather than the
    anchor's top, because a question number centred against a tall display
    fraction sits below the fraction's first line by construction. On page 16 of
    the sample paper Q21's numerator starts at y=64.4 while its ``21`` corrects
    to y=71.3: content above the *anchor*, but not above the boundary at y=68.3,
    and it belongs to Q21 rather than to the question on the previous page.
    """
    return any(line.y1 <= limit for line in furniture.body_lines(page)) or any(
        rect.y1 <= limit for rect in figures.figures
    )


def build_questions(
    pages: list[PageGeometry],
    furniture: Furniture,
    calibration: Calibration,
    start_page: int,
    config: ExtractConfig,
    end_page: int | None = None,
) -> tuple[list[Question], list[PageResult]]:
    """Turn page geometry into questions with one band per page occupied.

    Continuation detection: a page with content wholly above its first question
    boundary — or with no question number at all — opens with the tail of the
    previous question, so its leading band is appended to that question rather
    than starting a new one. A page whose first part label is ``(a)``/``(i)``
    falls out of the same test, since the part label is content and there is no
    anchor above it.

    An anchorless page is only a continuation if it carries content: a page
    printed ``BLANK PAGE``, or one whose body band is empty, is padding and is
    skipped rather than handed to the question above it.

    ``end_page`` is the last page of the paper proper, where one is marked. Pages
    beyond it are skipped outright — an answer key looks exactly like a question
    page to every test here, so the only reliable thing to know about it is that
    it lies past the end.
    """
    body_pages = [geom for geom in pages if geom.number >= start_page]
    # Anchors are not looked for past the end of the paper at all. Sequence
    # validation is document-wide, so leaving an answer key in would fill the
    # manifest with out-of-sequence warnings about numbers no question was ever
    # going to be built from.
    anchors_by_page = _detect_anchors(
        [geom for geom in body_pages if end_page is None or geom.number <= end_page],
        furniture,
        calibration,
        config,
    )

    questions: dict[int, Question] = {}
    results: list[PageResult] = []
    previous_number: int | None = None

    for geom in body_pages:
        result = PageResult(page=geom.number, has_text=geom.has_text)
        results.append(result)

        if end_page is not None and geom.number > end_page:
            # Asked before anything else: nothing about a page past the end of the
            # paper needs deciding, and every other test would guess.
            result.skip_reason = f"after the end-of-paper marker on page {end_page}"
            continue

        if not geom.has_text:
            result.needs_review = True
            result.review_reason = "no extractable text (possible scanned page)"
            log.warning(
                "page %d: no extractable text - emitting the page unannotated for review",
                geom.number,
            )
            continue

        band_limits = furniture.band(geom.number)
        figures = collect_figures(geom, band_limits, config)
        grid = detect_grid(geom, band_limits, config)
        if grid is not None:
            # A grid rule is a thin full-width stroke, which is what a divider is
            # too, so every horizontal line of the grid has just been recorded as
            # a question separator. Drop them before anything reads dividers: a
            # boundary snapped to one wins outright over the whitespace, and the
            # last one would pass for the page's bottom edge. Rules printed clear
            # of the grid are left alone - those are still real separators.
            figures.dividers = [
                rule for rule in figures.dividers if not grid.holds(rule)
            ]
            log.info(
                "page %d: graph grid (%d x %d rules, pitch %.1f x %.1f); "
                "the whole page belongs to one question",
                geom.number,
                grid.columns,
                grid.rows,
                grid.column_pitch,
                grid.row_pitch,
            )
        intervals = _merged_intervals(geom, furniture, figures)
        anchors = anchors_by_page.get(geom.number, [])
        result.figures = figures
        result.body_band = band_limits
        result.anchors = anchors
        result.grid = grid

        if not anchors:
            # An anchorless page is either a continuation or padding, and only the
            # page's content can say which. Asked before the review branch below,
            # because a page holding nothing but header and footer is a blank page,
            # not a page anyone needs to look at.
            skip = blank_page_reason(furniture.body_lines(geom), figures, config)
            if skip is not None:
                result.skip_reason = skip
                log.info("page %d: no question content (%s); skipping", geom.number, skip)
                # Nothing is open across an intentionally blank page.
                previous_number = None
                continue

        if not intervals:
            result.needs_review = True
            result.review_reason = "no body content found inside the page's body band"
            log.warning("page %d: no body content inside the body band", geom.number)
            continue

        content_top = _first_content_top(geom, furniture, figures)
        first_boundary = (
            _snap_boundary(anchors[0].top, intervals, figures, band_limits.top, config)
            if anchors
            else None
        )
        is_continuation = (
            _has_content_above(geom, furniture, figures, first_boundary)
            if first_boundary is not None
            else True
        )
        if is_continuation:
            result.continuation_note = _continuation_note(geom, furniture)

        page_bands: list[Band] = []
        continuation_bottom: float | None = None

        if is_continuation:
            bottom = (
                first_boundary
                if first_boundary is not None
                else _page_bottom(intervals, figures, band_limits)
            )
            continuation_bottom = bottom
            if previous_number is None:
                result.needs_review = True
                result.review_reason = (
                    "page opens mid-question but no question is open"
                )
                log.warning(
                    "page %d: looks like a continuation but no question is open "
                    "(check --start-page, or a blank page precedes it)",
                    geom.number,
                )
            else:
                band = _make_band(
                    geom,
                    previous_number,
                    band_limits.top,
                    bottom,
                    figures,
                    calibration,
                    config,
                    is_continuation=True,
                    band_limits=band_limits,
                    grid=grid,
                )
                if band is not None:
                    page_bands.append(band)

        for index, anchor in enumerate(anchors):
            if index > 0:
                # Share the boundary with the question above: no gap, no overlap.
                top = _snap_boundary(
                    anchor.top, intervals, figures, anchors[index - 1].top, config
                )
            elif continuation_bottom is not None:
                top = continuation_bottom
            else:
                # Nothing above this anchor belongs to another question — that is
                # what the continuation test just established — so start at the
                # page's highest content rather than at the anchor, which a tall
                # display fraction reaches above.
                top = max(
                    band_limits.top,
                    (content_top if content_top is not None else anchor.top)
                    - config.band_top_pad,
                )

            if index + 1 < len(anchors):
                bottom = _snap_boundary(
                    anchors[index + 1].top, intervals, figures, anchor.top, config
                )
            else:
                bottom = _page_bottom(intervals, figures, band_limits)

            band = _make_band(
                geom,
                anchor.number,
                top,
                bottom,
                figures,
                calibration,
                config,
                is_continuation=False,
                band_limits=band_limits,
                grid=grid,
            )
            if band is not None:
                page_bands.append(band)
                previous_number = anchor.number

        if not page_bands and not result.needs_review:
            result.needs_review = True
            result.review_reason = "no question boundaries could be derived"
            log.warning("page %d: no question boundaries could be derived", geom.number)

        result.bands = page_bands
        for band in page_bands:
            question = questions.setdefault(band.number, Question(number=band.number))
            band.segment = len(question.bands) + 1
            question.bands.append(band)

    ordered = [questions[number] for number in sorted(questions)]
    return ordered, results


def _detect_anchors(
    pages: list[PageGeometry],
    furniture: Furniture,
    calibration: Calibration,
    config: ExtractConfig,
) -> dict[int, list[Anchor]]:
    """Detect anchors on every page, then validate the sequence document-wide.

    Sequence validation has to be global: a stray gutter number is only
    recognisable as out of order relative to the questions on earlier pages.
    """
    per_page: dict[int, list[Anchor]] = {}
    flat: list[Anchor] = []
    for geom in pages:
        if not geom.has_text:
            continue
        found = find_page_anchors(furniture.body_lines(geom), calibration, config)
        per_page[geom.number] = found
        flat.extend(found)

    kept = set(map(id, filter_sequence(flat, config)))
    return {
        page: [anchor for anchor in anchors if id(anchor) in kept]
        for page, anchors in per_page.items()
    }
