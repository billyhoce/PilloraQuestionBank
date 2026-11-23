"""Leading-token classification.

Shared by calibration, furniture detection and anchor detection, all of which
need to recognise a bare question number before any of them can run.
"""

from __future__ import annotations

import re

ANCHOR_RE = re.compile(r"\d+\.?")
"""A top-level question number: digits, optionally followed by a full stop."""

PART_RE = re.compile(r"\(?(?:[a-z]{1,2}|[ivx]{1,4})[).]", re.IGNORECASE)
"""A part or subpart label: ``(a)``, ``a)``, ``(i)``, ``ii.`` and friends."""


def is_anchor_token(token: str) -> bool:
    """True when a leading token looks like a top-level question number."""
    return ANCHOR_RE.fullmatch(token) is not None


_OCR_DIGITS = str.maketrans(
    {
        "l": "1",
        "I": "1",
        "i": "1",
        "|": "1",
        "t": "1",
        "O": "0",
        "o": "0",
        "D": "0",
        "S": "5",
        "s": "5",
        "B": "8",
        "Z": "2",
        "z": "2",
        "g": "9",
    }
)
"""Letters an OCR pass commonly returns in place of a digit."""


def repaired_anchor_number(token: str) -> int | None:
    """The question number a garbled gutter token could be, or ``None``.

    Scanned papers reach the extractor with an OCR text layer, and a question
    number in the gutter is the worst possible place for it to slip: the whole
    page hangs off that one token. One sample paper renders ``13`` as ``t3`` and
    the question is lost, along with the page it opens.

    Three guards, each earning its place against a real corpus false positive:

    * **at least one certain digit**, so a token of pure letters is never read as
      a number;
    * **at least one substitution**, so ``8........`` — a dotted answer line on an
      answer script — stays rejected, being digits and dots rather than a
      near miss;
    * **two characters at most**, which is what question numbers are, and which
      bounds the damage.

    None of that is what makes the repair safe. What makes it safe is the caller:
    :func:`anchors.filter_sequence` accepts a repaired number only when it
    continues the question sequence exactly.
    """
    core = token.rstrip(".")
    if is_anchor_token(token) or len(core) > 2 or not any(c.isdigit() for c in core):
        return None
    repaired = core.translate(_OCR_DIGITS)
    if repaired == core or not repaired.isdigit():
        return None
    return int(repaired)


def repaired_label_number(label: str) -> int | None:
    """The question number an OCR-garbled answer-key label could open with.

    :func:`repaired_anchor_number` for the token before a label's first bracket
    (``l(a)`` -> 1), less its "one certain digit" guard. OCR reads a scanned
    key's question cell alone, so a lone ``l`` there is far likelier a ``1`` than
    in a question paper's gutter, and the caller (:mod:`.tablequestions`) accepts
    the repair only when the next number read agrees. Still two characters at
    most, and at least one substitution.
    """
    core = label.strip().split()[0].split("(")[0].rstrip(".") if label.strip() else ""
    if not core or len(core) > 2:
        return None
    repaired = core.translate(_OCR_DIGITS)
    if repaired == core or not repaired.isdigit():
        return None
    return int(repaired)


LABELLED_NUMBER_RE = re.compile(r"(\d+)\.?(?=$|[\s(]|[a-z](?:$|[\s(]))")
"""A question number opening an answer-key label: ``5``, ``5.``, ``5(iii)``,
``13(i)(b)``, ``10 (a)``, and the unbracketed ``2a`` and ``4b(i)`` of the Nan Hua
WA1 key. The number must end the token or be followed by a part label — one
letter counts only when the token ends after it or a bracket follows — so
``2x+1``, ``12xy`` or ``0.631`` in an answer is not read as one."""


def leading_question_number(text: str) -> int | None:
    """The question number an answer-key row label opens with, or ``None``.

    An answer key labels its rows with the number and the part run together —
    ``5(iii)`` — which :func:`is_anchor_token` rightly rejects, since in a
    question paper that token is never a bare gutter number. Only the number is
    read here; what the part label says is left to whoever groups the rows.
    """
    match = LABELLED_NUMBER_RE.match(text.strip())
    return int(match.group(1)) if match else None


def is_part_label(token: str) -> bool:
    """True when a leading token looks like a part label such as ``(a)``.

    Used only for continuation detection — a part label must never become an
    anchor, even when it shares a row with the question number.
    """
    return PART_RE.fullmatch(token) is not None
