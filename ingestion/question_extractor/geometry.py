"""Text and vector geometry extraction from a PDF page.

This is the only module that talks to PyMuPDF's extraction API. Everything
downstream works on the plain dataclasses defined here, which keeps the
detection logic testable and free of PDF-library detail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pymupdf

from .tokens import is_anchor_token

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Span:
    """One run of text within a line, with its own box.

    Carried because a line's own box is too coarse to trim a crop against, and
    because deciding whether a span *is* a question number needs its text, not
    just the line's leading token.
    """

    rect: pymupdf.Rect
    text: str
    content_x0: float | None = None
    """x0 of the text past a leading question number, when the span sets both.

    ``rect`` covers the whole run, so on a span like ``10 (a) `` it starts in the
    number gutter and says nothing about where the text beside the number begins.
    The characters do, and this is what they say; ``None`` when the span does not
    open with a number followed by more text. See
    :func:`_x0_after_leading_number`.
    """


@dataclass(frozen=True)
class TextLine:
    """One extracted line of text with the geometry the detectors care about."""

    page: int
    """1-based PDF page number."""
    rect: pymupdf.Rect
    text: str
    leading_token: str
    """First whitespace-separated token of the leftmost span on the line."""
    leading_x: float
    """x0 of that leftmost span — the value the gutter test is run against."""
    spans: tuple[Span, ...] = ()
    """The line's visible spans, ordered left to right.

    ``rect`` spans the whole line, which is too coarse to trim a crop against: on
    a row like ``13  Angle ABC …`` it starts in the number gutter. The individual
    span boxes are what say where the content column really begins.
    """

    @property
    def x0(self) -> float:
        return self.rect.x0

    @property
    def y0(self) -> float:
        return self.rect.y0

    @property
    def x1(self) -> float:
        return self.rect.x1

    @property
    def y1(self) -> float:
        return self.rect.y1

    @property
    def height(self) -> float:
        return self.rect.height

    def shares_row_with(self, other: "TextLine", tol: float) -> bool:
        """True when two lines sit on the same visual row, allowing ``tol`` slack.

        Uses vertical-span overlap rather than equal y0, because a question
        number is often centred against a taller neighbour (in the sample paper
        Q2's ``2`` sits at y=268.2 while its own text line starts at y=267.0).
        """
        return self.y0 - tol < other.y1 and other.y0 - tol < self.y1

    def vertical_overlap(self, other: "TextLine") -> float:
        """Height shared by two lines; zero or negative when they do not overlap."""
        return min(self.y1, other.y1) - max(self.y0, other.y0)

    def overlaps_row(self, other: "TextLine", min_fraction: float = 0.5) -> bool:
        """True when two lines genuinely overlap, not merely sit close together.

        The slack in :meth:`shares_row_with` is right for pulling a centred
        question number together with its text, but too generous for deciding
        that two lines are side by side: consecutive footer lines are often a
        fraction of a point apart and would pass it.
        """
        shortest = min(self.height, other.height)
        if shortest <= 0:
            return self.vertical_overlap(other) > 0
        return self.vertical_overlap(other) >= min_fraction * shortest

    def content_ink(self, x_cut: float) -> pymupdf.Rect | None:
        """Box of this line's ink right of ``x_cut``, or ``None`` if it has none.

        The line's own question number is left out. It has to be: a two-digit
        number in the sample paper runs from x=64.82 to x=79.82 against an
        ``x_cut`` of 79.16, so counting its last two thirds of a point would pin
        every crop's left edge back onto the cut and there would be nothing to
        trim. A span straddling the cut that is *not* the question number is body
        text — an instruction line set wider than the content column — and does
        count, clamped to the cut, so such a paper keeps the edge it has today
        rather than being clipped harder.

        The test is on the span's own text, not on the line's leading token: a PDF
        that sets ``13  Angle ABC`` as a single span must not lose ``Angle ABC``
        along with the number. Such a span is not clamped to the cut either — that
        put the edge back on ``x_cut`` just as surely, and it is the common case on
        a scan, where OCR sets the number and the text beside it as one run: the
        sample scan's p15 offers ``10 (a) `` boxed 61.6-111.9, which clamped to a
        cut of 71.5 while ``(a)`` starts at 87.1. Only the number's own characters
        are dropped, leaving the rest of the span with the box its characters give
        it (:attr:`Span.content_x0`).

        A span opening with a number is read as a numbered line only when it starts
        left of the cut, which is the gutter: a body line beginning with a year
        sits in the content column and keeps its number.
        """
        box: pymupdf.Rect | None = None
        for index, span in enumerate(self.spans):
            rect = span.rect
            if rect.x1 <= x_cut:
                continue  # wholly in the gutter
            if index == 0 and rect.x0 < x_cut:
                if is_anchor_token(span.text.strip()):
                    continue  # the question number alone, overhanging the cut
                if span.content_x0 is not None:
                    rect = pymupdf.Rect(span.content_x0, rect.y0, rect.x1, rect.y1)
                    if rect.is_empty:
                        continue
            clipped = pymupdf.Rect(max(rect.x0, x_cut), rect.y0, rect.x1, rect.y1)
            box = clipped if box is None else box | clipped
        return box


@dataclass
class PageGeometry:
    """Everything extracted from a single page."""

    number: int
    """1-based PDF page number."""
    rect: pymupdf.Rect
    lines: list[TextLine] = field(default_factory=list)
    image_rects: list[pymupdf.Rect] = field(default_factory=list)
    drawing_rects: list[pymupdf.Rect] = field(default_factory=list)
    rule_segments: list[pymupdf.Rect] = field(default_factory=list)
    """Every axis-aligned straight piece the page draws, path by path item.

    ``drawing_rects`` holds one box per *path*, which is right for unioning a
    figure but useless for reading a ruled table: a table drawn as one stroked
    path would arrive as a single box the size of the table. These are the
    path's pieces — each horizontal or vertical line, each filled rectangle (a
    word processor draws a rule as a thin fill), and each side of a stroked
    rectangle (a cell border). A piece drawn as a stroke has zero thickness;
    deciding which pieces are thin and long enough to be rules is the reader's
    job (:mod:`.tables`), not this module's.
    """

    @property
    def width(self) -> float:
        return self.rect.width

    @property
    def height(self) -> float:
        return self.rect.height

    @property
    def has_text(self) -> bool:
        return bool(self.lines)

    def has_page_sized_image(self, frac: float) -> bool:
        """True when a whole-page image covers this page: a scan, not a layout.

        Such a page has no box geometry to trim against. Its one image box is
        discarded as a background fill (it covers everything, so it locates
        nothing), and a scan carries no vector paths, which leaves the text layer
        as the only ink anything downstream can see — and the text layer misses
        every drawn diagram on the page.

        ``frac`` is ``figure_max_area_frac``, the same threshold that discards the
        box, so the test and the discard cannot drift apart.
        """
        page_area = max(self.width * self.height, 1.0)
        return any(
            not rect.is_infinite and rect.get_area() >= frac * page_area
            for rect in self.image_rects
        )


def _visible_spans(spans: list[dict]) -> list[dict]:
    """The spans on a line that carry visible text, ordered left to right."""
    return sorted(
        (s for s in spans if s["text"].strip()), key=lambda s: s["bbox"][0]
    )


def _x0_after_leading_number(span: dict) -> float | None:
    """x0 of a span's text past a leading question number, or ``None``.

    Only the number's own characters are skipped, and the whitespace after them:
    the answer is the box of the first character that is neither. ``None`` unless
    the span opens with a question number and carries text after it.

    Reads the character boxes, which is the whole point of extracting ``rawdict``
    rather than ``dict``. A merged span's box begins at the number, so on the
    sample scan's p15 ``10 (a) `` boxes 61.6-111.9 and the ``(`` this returns is
    at 87.1 — the difference between a crop edge on the gutter cut and one on the
    part label. OCR sets a character box to the glyph's advance width, which
    overstates it (that ``0`` is boxed to 79.9 and inked to 71.7); overstating is
    the safe direction here, because the box is only ever used to move the crop
    edge *right*, and ``crop_pad`` covers the difference.
    """
    text = span["text"]
    parts = text.split()
    if len(parts) < 2 or not is_anchor_token(parts[0]):
        return None
    chars = span.get("chars") or ()
    if len(chars) != len(text):  # pragma: no cover - defensive
        return None
    offset = len(text) - len(text.lstrip()) + len(parts[0])
    while offset < len(text) and text[offset].isspace():
        offset += 1
    if offset >= len(chars):
        return None
    return chars[offset]["bbox"][0]


def extract_page(page: pymupdf.Page) -> PageGeometry:
    """Pull text lines, image boxes and vector drawing boxes off one page."""
    geom = PageGeometry(number=page.number + 1, rect=pymupdf.Rect(page.rect))

    # ``rawdict`` rather than ``dict`` for the character boxes, which is what lets
    # a span holding both the question number and the text beside it be split at
    # the right place. It carries no measurable cost: over the 72-page sample scan
    # the two extractions time the same, to the millisecond.
    for block in page.get_text("rawdict")["blocks"]:
        if block["type"] != 0:  # 0 == text; images are collected separately
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                span["text"] = "".join(char["c"] for char in span["chars"])
            visible = _visible_spans(line["spans"])
            if not visible:
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text:
                continue
            lead = visible[0]
            token = lead["text"].strip().split()[0]
            geom.lines.append(
                TextLine(
                    page=geom.number,
                    rect=pymupdf.Rect(line["bbox"]),
                    text=text,
                    leading_token=token,
                    leading_x=lead["bbox"][0],
                    spans=tuple(
                        Span(
                            rect=pymupdf.Rect(s["bbox"]),
                            text=s["text"],
                            content_x0=_x0_after_leading_number(s),
                        )
                        for s in visible
                    ),
                )
            )

    geom.lines.sort(key=lambda ln: (ln.y0, ln.x0))

    try:
        for info in page.get_image_info():
            geom.image_rects.append(pymupdf.Rect(info["bbox"]))
    except Exception as exc:  # pragma: no cover - defensive, malformed PDFs
        log.warning("page %d: could not read image boxes (%s)", geom.number, exc)

    try:
        for drawing in page.get_drawings():
            geom.drawing_rects.append(pymupdf.Rect(drawing["rect"]))
            geom.rule_segments.extend(_axis_aligned_pieces(drawing))
    except Exception as exc:  # pragma: no cover - defensive, malformed PDFs
        log.warning("page %d: could not read vector drawings (%s)", geom.number, exc)

    return geom


_AXIS_TOL = 0.1
"""Points a line's ends may differ across its axis and still be horizontal or
vertical. Exactly the tolerance of the arithmetic, not a judgement about rules."""


def _axis_aligned_pieces(drawing: dict) -> list[pymupdf.Rect]:
    """The horizontal and vertical pieces of one path, as boxes.

    A line gives a zero-thickness box. A rectangle gives itself when the path is
    filled only — a thin fill is a rule, a fat one shading the reader will drop —
    and its four sides when the path is stroked, since a stroked rectangle is a
    border and not a filled area. Curves and slanted lines are never rules.
    """
    stroked = "s" in (drawing.get("type") or "")
    pieces: list[pymupdf.Rect] = []
    for item in drawing.get("items", ()):
        kind = item[0]
        if kind == "l":
            a, b = item[1], item[2]
            if abs(a.y - b.y) <= _AXIS_TOL or abs(a.x - b.x) <= _AXIS_TOL:
                pieces.append(
                    pymupdf.Rect(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))
                )
        elif kind in ("re", "qu"):
            if kind == "qu":
                if not item[1].is_rectangular:
                    continue
                rect = pymupdf.Rect(item[1].rect)
            else:
                rect = pymupdf.Rect(item[1])
            if not stroked:
                pieces.append(rect)
                continue
            x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
            pieces.extend(
                (
                    pymupdf.Rect(x0, y0, x1, y0),
                    pymupdf.Rect(x0, y1, x1, y1),
                    pymupdf.Rect(x0, y0, x0, y1),
                    pymupdf.Rect(x1, y0, x1, y1),
                )
            )
    return pieces


def extract_document(doc: pymupdf.Document) -> list[PageGeometry]:
    """Extract geometry for every page, in document order."""
    return [extract_page(doc[i]) for i in range(doc.page_count)]
