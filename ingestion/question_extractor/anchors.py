"""Question-number anchor detection.

A *top-level question anchor* is a bare number sitting in the left-hand number
gutter. The gutter test is what separates a real anchor from a number that
merely occurs in the body text — ``8`` inside ``{2, 3, 5, 7, 11}`` matches the
same regex, but its x-position is in the content column, not the gutter.

The anchor fixes only *where a question begins vertically*. Where the crop
begins horizontally is ``Calibration.x_cut``; the two are deliberately separate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .calibration import Calibration
from .config import ExtractConfig
from .geometry import TextLine
from .tokens import is_anchor_token, repaired_anchor_number

log = logging.getLogger(__name__)


@dataclass
class Anchor:
    """A detected question start."""

    page: int
    number: int
    line: TextLine
    """The gutter line carrying the number."""
    top: float
    """Corrected top of the question: the highest y0 on the anchor's row."""
    repaired: bool = False
    """True when the number was read through an OCR repair rather than verbatim.

    Such an anchor is only provisional: :func:`filter_sequence` keeps it solely
    when it continues the question sequence.
    """

    def entry(self) -> dict:
        """JSON-ready; ``line`` is a :meth:`.geometry.TextLine.entry`."""
        return {
            "page": self.page,
            "number": self.number,
            "line": self.line.entry(),
            "top": self.top,
            "repaired": self.repaired,
        }

    @classmethod
    def from_entry(cls, entry: dict) -> Anchor:
        return cls(
            entry["page"],
            entry["number"],
            TextLine.from_entry(entry["line"]),
            entry["top"],
            entry["repaired"],
        )


def _corrected_top(anchor_line: TextLine, body_lines: list[TextLine], config: ExtractConfig) -> float:
    """Return the true top of the question that starts at ``anchor_line``.

    The number itself is frequently centred against a taller neighbour, so its
    own y0 is not the top of the question. Taking the highest y0 of everything
    on the same row fixes that.
    """
    tops = [ln.y0 for ln in body_lines if ln.shares_row_with(anchor_line, config.row_tol)]
    return min(tops) if tops else anchor_line.y0


def find_page_anchors(
    body_lines: list[TextLine],
    calibration: Calibration,
    config: ExtractConfig,
) -> list[Anchor]:
    """Find every top-level anchor on one page, top to bottom.

    Only the *leftmost* gutter token on a row can be the anchor, so a line such
    as ``7   (a)  Expand ...`` yields ``7`` and never ``(a)``. A token that only
    looks like a number once OCR damage is undone is a candidate too, and the same
    leftmost rule settles a row carrying both: a verbatim number left of a
    repaired one wins, as it should.
    """
    candidates: list[tuple[TextLine, int, bool]] = []
    for line in body_lines:
        if line.leading_x > calibration.x_cut:
            continue
        if is_anchor_token(line.leading_token):
            candidates.append((line, int(line.leading_token.rstrip(".")), False))
        else:
            number = repaired_anchor_number(line.leading_token)
            if number is not None:
                candidates.append((line, number, True))

    anchors: list[Anchor] = []
    for line, number, repaired in sorted(candidates, key=lambda c: (c[0].y0, c[0].x0)):
        if anchors and line.shares_row_with(anchors[-1].line, config.row_tol):
            continue  # already have the leftmost gutter token for this row
        anchors.append(
            Anchor(
                page=line.page,
                number=number,
                line=line,
                top=_corrected_top(line, body_lines, config),
                repaired=repaired,
            )
        )

    for anchor in anchors:
        _warn_if_text_crosses_cut(anchor, calibration)

    return anchors


def _warn_if_text_crosses_cut(anchor: Anchor, calibration: Calibration) -> None:
    """Warn when an anchor line carries body text that ``x_cut`` would slice.

    Normally the number is a line of its own and the body text starts in the
    content column. If a paper puts both in one span, cropping at ``x_cut``
    would cut through words, so it is worth flagging.
    """
    if anchor.line.text != anchor.line.leading_token and anchor.line.x1 > calibration.x_cut:
        log.warning(
            "page %d: question %d shares its line with body text starting left of "
            "x_cut=%.1f (%r) - the crop may clip it",
            anchor.page,
            anchor.number,
            calibration.x_cut,
            anchor.line.text[:60],
        )


def filter_sequence(anchors: list[Anchor], config: ExtractConfig) -> list[Anchor]:
    """Drop anchors that break the question numbering sequence.

    Papers number questions upwards, so a number that repeats or goes backwards
    is a false positive (a stray gutter figure, a mis-detected page number).
    Gaps are allowed but reported, since they usually mean a genuine anchor was
    missed rather than that the paper skips a number.

    That upward run is also what admits an OCR-repaired number, and the only thing
    that does: a repaired anchor is kept when it is exactly the next question in
    the sequence, and dropped otherwise. Never the first anchor of a paper, and
    never across a gap — so a garbled token has to land on the one number the
    paper is already expecting before it is believed. Each repair that is accepted
    joins the sequence, which is what lets consecutive garbled numbers chain.
    """
    kept: list[Anchor] = []
    for anchor in anchors:
        if anchor.number > config.max_anchor_number:
            log.warning(
                "page %d: ignoring implausible question number %d", anchor.page, anchor.number
            )
            continue
        if anchor.repaired:
            if not kept or anchor.number != kept[-1].number + 1:
                continue
            # Warned, not merely logged: a repair is a guess that happened to fit,
            # so it belongs in the manifest where someone will see it.
            log.warning(
                "page %d: reading gutter token %r as question number %d (OCR repair)",
                anchor.page,
                anchor.line.leading_token,
                anchor.number,
            )
            kept.append(anchor)
            continue
        if kept and anchor.number <= kept[-1].number:
            log.warning(
                "page %d: ignoring out-of-sequence question number %d (previous was %d)",
                anchor.page,
                anchor.number,
                kept[-1].number,
            )
            continue
        if kept and anchor.number != kept[-1].number + 1:
            log.warning(
                "page %d: question numbering jumps from %d to %d - an anchor may have "
                "been missed",
                anchor.page,
                kept[-1].number,
                anchor.number,
            )
        kept.append(anchor)
    return kept
