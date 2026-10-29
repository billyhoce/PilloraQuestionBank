"""Telling a page that carries no question from one that does.

Papers pad themselves out. A paper printed for double-sided binding ends with a
page whose entire body is the words ``BLANK PAGE``, and the same trick appears
mid-paper to start a section on a fresh sheet.

Such a page has no question number on it, which is exactly the signature of a
*continuation* page — the tail of a question that began on the page before. Left
alone, the blank page is handed to the previous question and contributes a
rectangle covering the whole sheet. The difference is not geometric, so it cannot
be settled by the boundary logic: it comes down to whether there is any content
on the page at all, and to the marker the paper prints when there is not.

The same reasoning covers the *end* of a paper. A PDF very often holds more than
the question paper — an answer key, a second paper, a full marking scheme — and
the only thing marking the join is the line the paper prints to say it is over.
Nothing geometric distinguishes a marking scheme from a question page, so this is
where that line is recognised too.
"""

from __future__ import annotations

import re

from .config import ExtractConfig
from .figures import PageFigures, real_figures
from .geometry import TextLine

_SPACES = re.compile(r"\s+")


def _normalise(texts: list[str]) -> str:
    """Join a page's text into one comparable line."""
    return _SPACES.sub(" ", " ".join(texts)).strip().casefold()


def blank_page_reason(
    body_lines: list[TextLine], figures: PageFigures, config: ExtractConfig
) -> str | None:
    """Why this page carries no question content, or ``None`` if it does.

    Two signals, both requiring the page to hold no real figure — divider rules
    are already excluded by :func:`figures.collect_figures`, so a page carrying
    nothing but a rule still reads as blank:

    * an **empty body band**: whatever text the page has is running header and
      footer, which every page has and no question owns;
    * a **blank-page marker** as the only text. The length cap matters: a
      question that tells a candidate to leave a page blank is not itself blank.
    """
    boxes = real_figures(figures.figures, config)
    texts = [line.text.strip() for line in body_lines if line.text.strip()]

    if not texts and not boxes:
        return "body band is empty"

    if not boxes and texts:
        joined = _normalise(texts)
        if len(joined) <= config.blank_page_max_chars and _is_marker(joined, config):
            return f"marked blank ({texts[0]!r})"

    return None


def end_of_paper_y(body_lines: list[TextLine], config: ExtractConfig) -> float | None:
    """``y0`` of the highest end-of-paper marker among these lines, or ``None``.

    Matched per line rather than over the page's joined text, because the marker's
    own position is the answer wanted: it is where the last question stops. The
    highest one wins on the rare page carrying two.

    The line length cap is all that separates the marker from a sentence
    mentioning it — and across the sample corpus it is enough, every one of the 75
    marker lines being 18 characters or fewer with no long line matching at all.
    """
    tops = [
        line.y0
        for line in body_lines
        if len(line.text.strip()) <= config.end_of_paper_max_chars
        and any(re.search(pattern, line.text, re.IGNORECASE) for pattern in config.end_of_paper_patterns)
    ]
    return min(tops) if tops else None


def _is_marker(joined: str, config: ExtractConfig) -> bool:
    """Whether a page's whole text *is* a blank-page marker.

    Matching anywhere in the text is not enough. ``(c) Use the blank page
    opposite.`` is a continuation instruction that happens to contain the words,
    so the match must also account for most of what is on the page.
    """
    for pattern in config.blank_page_patterns:
        match = re.search(pattern, joined)
        if match is None:
            continue
        if len(match.group(0)) >= config.blank_page_marker_frac * len(joined):
            return True
    return False
