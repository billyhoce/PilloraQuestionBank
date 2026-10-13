"""Running header / footer detection.

Exam papers repeat a school name across the top and a running footer plus page
number across the bottom of every page. Neither belongs to a question, and the
footer matters especially: the last question on a page ends at the bottom of the
body, and without footer detection that boundary would swallow the footer into
the crop.

Furniture is found by repetition — a line at roughly the same height with the
same text (digits normalised away, so ``Page 3`` and ``Page 4`` match) on most
pages of the paper. The result is a per-page *body band*: the vertical slice
between the header and the footer that questions may occupy.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from dataclasses import dataclass, field

from .config import ExtractConfig
from .geometry import PageGeometry, TextLine
from .tokens import is_anchor_token

log = logging.getLogger(__name__)

_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")

FurnitureKey = tuple[int, str]


def _normalise(text: str) -> str:
    """Collapse a line to a repetition-comparable form."""
    return _DIGITS.sub("#", _SPACES.sub(" ", text.strip().casefold()))


def _key(line: TextLine, key_chars: int = 0) -> FurnitureKey:
    """Bucket a line by rounded height and normalised text.

    Only the first ``key_chars`` characters of the text are compared (0 compares
    all of it). Running footers commonly differ between recto and verso — in one
    sample paper the odd pages read ``… /prelim/2023 [turn over`` and the even
    pages ``… s4 prelim/2023`` — which splits one footer into two counts of ten
    against a threshold of eleven, and neither is detected. The two agree for
    their first 36 characters.

    The height bucket, by contrast, cannot be loosened: measured across the sample
    corpus, dropping it makes mark brackets ``[2]`` register as repeating
    furniture in 38 papers and part labels ``(a)`` in 7, deleting question content
    from 82 of 111 papers.
    """
    text = _normalise(line.text)
    return (round(line.y0 / 2.0), text[:key_chars] if key_chars else text)


@dataclass(frozen=True)
class BodyBand:
    """The vertical slice of a page that questions may occupy."""

    top: float
    bottom: float

    def entry(self) -> dict:
        """JSON-ready: ``{"top", "bottom"}`` in PDF points."""
        return {"top": self.top, "bottom": self.bottom}

    @classmethod
    def from_entry(cls, entry: dict) -> BodyBand:
        return cls(entry["top"], entry["bottom"])

    def contains(self, y0: float, y1: float) -> bool:
        """True when the midpoint of a span falls inside the band."""
        return self.top <= (y0 + y1) / 2.0 <= self.bottom


@dataclass
class Furniture:
    """Detected running header/footer, and the body band it leaves per page."""

    keys: set[FurnitureKey] = field(default_factory=set)
    bands: dict[int, BodyBand] = field(default_factory=dict)
    key_chars: int = 0
    """Prefix length the keys were built with, so lookups match how they were made."""

    def is_furniture(self, line: TextLine) -> bool:
        return _key(line, self.key_chars) in self.keys

    def band(self, page: int) -> BodyBand:
        return self.bands[page]

    def clip_band(self, page: int, bottom: float) -> None:
        """Pull a page's body band up to ``bottom``, never inverting or growing it.

        For content that is not repeated furniture but does not belong to a
        question either — an end-of-paper marker being the case in hand. Excluding
        it here rather than at each point of use means every stage that reads the
        page through :meth:`body_lines` is right about it at once.
        """
        band = self.bands[page]
        self.bands[page] = BodyBand(
            top=band.top, bottom=max(band.top + 1.0, min(band.bottom, bottom))
        )

    def body_lines(self, geom: PageGeometry) -> list[TextLine]:
        """Lines of a page that are inside the body band and not furniture."""
        band = self.bands[geom.number]
        return [
            line
            for line in geom.lines
            if band.contains(line.y0, line.y1) and not self.is_furniture(line)
        ]


def _row_has_companion_to_right(line: TextLine, geom: PageGeometry) -> bool:
    """True when another line genuinely shares this line's row, to its right.

    Deliberately uses the strict overlap test: a running footer's lines sit a
    fraction of a point apart, and with any slack the page number would appear
    to have a neighbour and so be mistaken for a question anchor.
    """
    return any(
        other is not line and other.x0 > line.x1 and other.overlaps_row(line)
        for other in geom.lines
    )


def _eligible(line: TextLine, geom: PageGeometry) -> bool:
    """Whether a line may be considered running furniture at all.

    A bare number that has body text to its right on the same row is a question
    anchor, not a page number. Without this guard a paper whose pages each open
    with a question number at the same height would have those anchors detected
    as a repeating "footer" and deleted.
    """
    if line.text == line.leading_token and is_anchor_token(line.leading_token):
        return not _row_has_companion_to_right(line, geom)
    return True


def detect_furniture(pages: list[PageGeometry], config: ExtractConfig) -> Furniture:
    """Find the running header/footer and derive each page's body band."""
    furniture = Furniture(key_chars=config.furniture_key_chars)
    if not pages:
        return furniture

    occurrences: dict[FurnitureKey, set[int]] = {}
    for geom in pages:
        top_limit = geom.rect.y0 + config.furniture_band_frac * geom.height
        bottom_limit = geom.rect.y1 - config.furniture_band_frac * geom.height
        for line in geom.lines:
            in_margin = line.y1 <= top_limit or line.y0 >= bottom_limit
            if not in_margin or not _eligible(line, geom):
                continue
            occurrences.setdefault(_key(line, furniture.key_chars), set()).add(geom.number)

    threshold = max(
        config.furniture_min_pages,
        math.ceil(config.furniture_min_page_frac * len(pages)),
    )
    furniture.keys = {key for key, seen in occurrences.items() if len(seen) >= threshold}

    _assign_bands(pages, furniture, config)
    if furniture.keys:
        log.debug("detected %d running header/footer line(s)", len(furniture.keys))
    else:
        log.debug("no running header/footer detected; using default page margins")
    return furniture


def _tail_footers(
    pages: list[PageGeometry], config: ExtractConfig
) -> dict[int, float]:
    """The ``y0`` of each page's trailing footer row, where one repeats.

    The repetition rule above needs a line on half the paper's pages, which a
    footer misses whenever it is printed on one side only — ``[Turn over`` on the
    odd pages and nothing on the even ones is common, and the sample corpus has 18
    papers whose footers survive into the body band for want of a page or two.
    Loosening that threshold is not an option: it starts deleting question content
    (see :func:`_key`).

    Being the **last row on the page**, inside the outer margin, is a different and
    much stronger signal, so a handful of pages is enough repetition to confirm it.
    The result feeds only the band's bottom edge — nothing needs to recognise these
    lines as furniture later, because a line below the band is already excluded.
    """
    candidates: dict[str, dict[int, float]] = {}
    for geom in pages:
        if not geom.lines:
            continue
        edge = geom.rect.y1 - config.furniture_tail_frac * geom.height
        lowest = max(line.y0 for line in geom.lines)
        if lowest < edge:
            continue
        for line in geom.lines:
            if abs(line.y0 - lowest) > config.row_tol or not _eligible(line, geom):
                continue
            text = _normalise(line.text)[: config.furniture_key_chars]
            # No height bucket: being the trailing row has already fixed the
            # position, and a footer drifts by a point or two between pages.
            candidates.setdefault(text, {})[geom.number] = line.y0

    tails: dict[int, float] = {}
    for seen in candidates.values():
        if len(seen) < config.furniture_tail_min_pages:
            continue
        for page, y0 in seen.items():
            tails[page] = min(tails.get(page, y0), y0)
    return tails


def _assign_bands(
    pages: list[PageGeometry], furniture: Furniture, config: ExtractConfig
) -> None:
    """Derive the body band per page, filling gaps from the paper-wide median.

    A page that happens to lack the header (a cover, say) inherits the median of
    the pages that have one, so its band stays consistent with the rest of the
    paper instead of falling back to a crude fixed margin.
    """
    raw_tops: dict[int, float] = {}
    raw_bottoms: dict[int, float] = {}
    tails = _tail_footers(pages, config)

    for geom in pages:
        top_limit = geom.rect.y0 + config.furniture_band_frac * geom.height
        bottom_limit = geom.rect.y1 - config.furniture_band_frac * geom.height
        headers = [
            line
            for line in geom.lines
            if furniture.is_furniture(line) and line.y1 <= top_limit
        ]
        footers = [
            line
            for line in geom.lines
            if furniture.is_furniture(line) and line.y0 >= bottom_limit
        ]
        if headers:
            raw_tops[geom.number] = max(line.y1 for line in headers) + config.furniture_pad
        if footers:
            raw_bottoms[geom.number] = min(line.y0 for line in footers) - config.furniture_pad

    median_top = statistics.median(raw_tops.values()) if raw_tops else None
    median_bottom = statistics.median(raw_bottoms.values()) if raw_bottoms else None

    for geom in pages:
        default_top = geom.rect.y0 + config.default_top_margin
        default_bottom = geom.rect.y1 - config.default_bottom_margin
        top = raw_tops.get(geom.number, median_top if median_top is not None else default_top)
        bottom = raw_bottoms.get(
            geom.number, median_bottom if median_bottom is not None else default_bottom
        )
        if geom.number in tails:
            bottom = min(bottom, tails[geom.number] - config.furniture_pad)
        # Never let furniture detection invert or collapse a page's body band.
        top = max(geom.rect.y0, min(top, geom.rect.y1))
        bottom = min(geom.rect.y1, max(bottom, top + 1.0))
        furniture.bands[geom.number] = BodyBand(top=top, bottom=bottom)
